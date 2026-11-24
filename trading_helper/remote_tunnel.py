"""Explicitly started temporary HTTPS access using an existing cloudflared."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


def cloudflared_path() -> str:
    # No downloads, shell commands, service installation or firewall changes.
    for root in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
        if root and (path := Path(root) / 'cloudflared' / 'cloudflared.exe').is_file():
            return str(path)
    return shutil.which('cloudflared') or ''


def tailscale_path() -> str:
    root = os.environ.get('ProgramFiles', '')
    path = Path(root) / 'Tailscale' / 'tailscale.exe'
    return str(path) if root and path.is_file() else shutil.which('tailscale') or ''


def stale_funnel_pids(local_origin, own_pid=None, processes=None):
    """PIDs of LEFTOVER Funnel sessions this helper itself started.

    Only `tailscale.exe funnel --https=8443 <this helper's local origin>`
    whose parent is this helper or no longer exists. Never the Tailscale
    service, its tray app, or a command the user runs in a live terminal.
    """
    own_pid = os.getpid() if own_pid is None else own_pid
    if processes is None:
        processes = _tailscale_processes()
    alive = {pid for pid, _parent, _cmd in processes} | set(_alive_pids())
    found = []
    for pid, parent, command in processes:
        words = command.replace('"', ' ').split()
        if ('funnel' in words and '--https=8443' in words and local_origin in words
                and (parent == own_pid or parent not in alive)):
            found.append(pid)
    return found


def _tailscale_processes():
    import subprocess
    script = ("Get-CimInstance Win32_Process -Filter \"Name='tailscale.exe'\" | "
              "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId,$_.ParentProcessId,$_.CommandLine }")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True,
                             text=True, timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.strip().split('|', 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def _alive_pids():
    import ctypes
    from ctypes import wintypes
    psapi = ctypes.WinDLL('psapi')
    buffer = (wintypes.DWORD * 8192)()
    size = wintypes.DWORD()
    if not psapi.EnumProcesses(buffer, ctypes.sizeof(buffer), ctypes.byref(size)):
        return []
    return list(buffer[:size.value // ctypes.sizeof(wintypes.DWORD)])


def end_stale_funnels(local_origin):
    import subprocess
    pids = stale_funnel_pids(local_origin)
    for pid in pids:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=5,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return pids


class QuickTunnel(QObject):
    ready = Signal(str)
    failed = Signal(str)
    changed = Signal()

    def __init__(self, parent=None, diagnostic_path=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._finished)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(60_000)
        self.timeout.timeout.connect(lambda: self._fail('手機連線逾時，請確認網路後重新開啟。'))
        self.url = ''
        self.message = '尚未開啟手機外網連線'
        self.connected = False
        self._buffer = ''
        self._folder = None
        self._stopping = False
        self._failed = False
        self.diagnostic_path = Path(diagnostic_path) if diagnostic_path else None
        self._tail = deque(maxlen=12)
        self._started_at = time.monotonic()

    def _record(self, event, **details):
        if self.diagnostic_path is None:
            return
        # Bounded local diagnostics, without URLs, credentials or local paths.
        def clean(value):
            value = re.sub(r'https?://\S+', '[網址]', str(value))
            value = re.sub(r'(?i)[a-z]:\\[^\s"<>]+', '[本機路徑]', value)
            value = re.sub(r'(?i)\b(token|authorization|cookie)\s*[:=]\s*\S+', r'\1=[隱藏]', value)
            return value[:400]
        record = dict(event=event, at_utc=datetime.now(timezone.utc).isoformat(),
                      elapsed_ms=round((time.monotonic()-self._started_at)*1000),
                      tail=[clean(line) for line in self._tail],
                      **{key:clean(value) for key,value in details.items()})
        try:
            path = self.diagnostic_path
            path.parent.mkdir(parents=True, exist_ok=True)
            previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() and path.stat().st_size < 256_000 else []
            if not isinstance(previous, list):
                previous = []
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps((previous+[record])[-20:], ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
        except (OSError, ValueError):
            pass  # Diagnostics must not change connection or trading behavior.

    @property
    def running(self):
        return self.process.state() != QProcess.NotRunning

    def start(self, local_origin: str):
        if self.running:
            raise ValueError('手機連線正在執行，請先停止。')
        if not re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', local_origin):
            raise ValueError('手機連線只能連到本程式的本機入口。')
        executable = cloudflared_path()
        if not executable:
            raise ValueError('尚未安裝 Cloudflare 連線工具，請先在電腦安裝 cloudflared。')
        self._stopping = self._failed = False
        self.connected = False
        self.url = self._buffer = ''
        self._tail.clear()
        self._started_at = time.monotonic()
        self.message = '正在建立手機網址…'
        self._folder = tempfile.TemporaryDirectory(prefix='helper-mobile-')
        config = Path(self._folder.name) / 'quick-tunnel.yaml'
        config.write_text('{}\n', encoding='utf-8')
        environment = QProcessEnvironment.systemEnvironment()
        for key in environment.keys():
            if key.startswith(('TUNNEL_', 'CLOUDFLARED_')):
                environment.remove(key)
        self.process.setProcessEnvironment(environment)
        self.process.setProgram(executable)
        self.process.setArguments([
            'tunnel', '--config', str(config), '--no-autoupdate',
            '--metrics', '127.0.0.1:0', '--protocol', 'http2',
            '--edge-ip-version', '4', '--url', local_origin,
        ])
        self.timeout.start()
        self.process.start()
        self._record('starting')
        self.changed.emit()

    def _read(self):
        self._consume(bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace'))

    def _consume(self, text):
        if self._stopping or self._failed:
            return
        self._buffer += text
        lines = self._buffer.split('\n')
        self._buffer = lines.pop()[-4096:]
        for line in lines:
            self._tail.append(line[-800:])
            match = re.search(r'https://([a-z0-9]+(?:-[a-z0-9]+)*)\.trycloudflare\.com(?=[\s|/]|$)', line)
            if match:
                self.url = match.group(0)
            if 'Registered tunnel connection' in line and self.url and not self.connected:
                self.connected = True
                self.timeout.stop()
                self.message = '手機外網連線已建立（臨時網址）'
                self._record('connected')
                self.ready.emit(self.url)
                self.changed.emit()
            elif 'Unregistered tunnel connection' in line and self.connected:
                self._fail('手機外網連線已中斷，請重新開啟；不會重送操作。')

    def _error(self, _error):
        if not self._stopping:
            self._fail('無法啟動手機連線工具，請確認工具與網路。')

    def _finished(self, exit_code=0, *_):
        if not self._stopping and not self._failed:
            self._read()
            self._fail('手機外網連線已結束；不會重送操作。', exit_code=exit_code)

    def _fail(self, message, **details):
        if self._failed or self._stopping:
            return
        self._failed = True
        self._record('failed', reason=message, process_error=self.process.errorString(), **details)
        self.stop()
        self.message = message
        self.failed.emit(message)
        self.changed.emit()

    def stop(self):
        self._stopping = True
        self.timeout.stop()
        self.connected = False
        self.url = ''
        if self.running:
            # Only our own child process; never touch another tunnel or broker.
            self.process.kill()
            self.process.waitForFinished(1500)
        if self._folder is not None:
            self._folder.cleanup()
            self._folder = None
        self.message = '手機外網連線已停止'
        self.changed.emit()


class FixedTunnel(QuickTunnel):
    """Own only a foreground Funnel session; never reset another service.

    Account login and the provider's first-use permission remain explicit user
    actions. No token, hostname, installer, or service is manufactured here.
    """
    def __init__(self, parent=None, diagnostic_path=None):
        super().__init__(parent, diagnostic_path)
        self.approval_url = ''
        self._available = False
        self.timeout.setInterval(180_000)
        self.timeout.timeout.disconnect()
        self.timeout.timeout.connect(lambda: self._fail('固定入口設定逾時，請完成 Tailscale 登入與允許設定後重試。'))
        self.message = '固定入口尚未設定'

    def start(self, local_origin):
        if self.running:
            raise ValueError('固定入口正在執行，請先停止。')
        if not re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', local_origin):
            raise ValueError('固定入口只能連到本程式的本機入口。')
        executable = tailscale_path()
        if not executable:
            raise ValueError('請先安裝 Tailscale 並登入，再按「建立固定入口」。不需要購買網域。')
        # A Funnel left behind by an earlier run (or a stop that did not
        # finish) holds port 8443 and makes the new one fail with
        # "listener already exists". End only those leftovers of ours.
        self._local_origin = local_origin
        ended = end_stale_funnels(local_origin)
        if ended:
            self._record('fixed_stale_ended', pids=ended)
        self._stopping = self._failed = self.connected = self._available = False
        self.url = self._buffer = self.approval_url = ''
        self._tail.clear()
        self._started_at = time.monotonic()
        self.message = '正在建立固定入口；首次請完成 Tailscale 的允許設定。'
        self.process.setProgram(executable)
        # No --bg / --yes: don't persist exposure or skip provider consent.
        self.process.setArguments(['funnel', '--https=8443', local_origin])
        self.timeout.start()
        self.process.start()
        self._record('fixed_starting')
        self.changed.emit()

    def _consume(self, text):
        if self._stopping or self._failed:
            return
        self._buffer += text
        lines = self._buffer.split('\n')
        self._buffer = lines.pop()[-4096:]
        for line in lines:
            # Provider approval URLs may contain tokens; never log them.
            approval = re.search(r'https://login\.tailscale\.com/[A-Za-z0-9_/?=&.%~-]+', line)
            if approval:
                self.approval_url = approval.group(0)
                self.message = '請按「允許固定入口」，完成首次設定。'
                self.changed.emit()
                continue
            self._tail.append(line[-800:])
            if 'Available on the internet:' in line:
                self._available = True
            match = re.search(r'https://([a-z0-9-]+\.)+[a-z0-9-]+\.ts\.net:8443/?(?=[\s|]|$)', line)
            if self._available and match and not self.connected:
                self.url = match.group(0).rstrip('/')
                self.connected = True
                self._retried = False
                self.timeout.stop()
                self.approval_url = ''
                self.message = '固定入口已準備好，請用手機掃碼。'
                self._record('fixed_connected')
                self.ready.emit(self.url)
                self.changed.emit()

    def _error(self, _error):
        if not self._stopping:
            self._fail('固定入口無法啟動，請確認已安裝並登入 Tailscale。')

    def stop(self):
        self.approval_url = ''
        self._available = False
        super().stop()

    def _finished(self, exit_code=0, *_):
        if not self._stopping and not self._failed:
            self._read()
            if (any('listener already exists' in line for line in self._tail)
                    and not getattr(self, '_retried', False)):
                # Port still held by a leftover of ours: clear it, retry once.
                self._retried = True
                self._record('fixed_retry_after_busy_port')
                self.start(self._local_origin)
                return
            self._fail('固定入口已停止，請確認 Tailscale 登入與允許設定後重試。', exit_code=exit_code)
