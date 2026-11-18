"""Opt-in loopback HTTP/WebSocket transport for the mobile control page.

External access requires an explicitly configured HTTPS reverse proxy. This
module never opens a LAN/public listener, runs a tunnel, or dispatches trades.
Qt owns the sockets; application commands remain on the application's thread.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from collections import deque
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QSslSocket
from PySide6.QtWebSockets import QWebSocketServer

COOKIE = "helper_remote"
MAX_MESSAGE = 16_384
SESSION_SECONDS = 180 * 24 * 60 * 60
_native_tls_ready = False


def use_windows_native_tls():
    """Do not let Qt scan unrelated OpenSSL plugins while selecting Schannel."""
    global _native_tls_ready
    if os.name != 'nt' or _native_tls_ready:
        return
    import PySide6
    try:
        source = Path(PySide6.__file__).parent / 'plugins' / 'tls' / 'qschannelbackend.dll'
        content = source.read_bytes()
        # A single versioned code cache, separate from settings/calibration.
        root = Path(tempfile.gettempdir()) / 'TradingWorkflowHelper_QtTLS' / hashlib.sha256(content).hexdigest()[:20]
        target = root / 'tls' / source.name
        if not target.exists() or target.read_bytes() != content:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(content)
            temporary.replace(target)
        original = QCoreApplication.libraryPaths()
        try:
            QCoreApplication.setLibraryPaths([str(root)])
            if not QSslSocket.setActiveBackend('schannel'):
                raise ValueError('Windows 加密連線元件無法啟用，手機連線未開啟。')
        finally:
            QCoreApplication.setLibraryPaths(original)
    except OSError as exc:
        raise ValueError('Windows 加密連線元件無法載入，手機連線未開啟。') from exc
    _native_tls_ready = True


def normalized_origin(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.path or parts.query or parts.fragment
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", parts.netloc)):
        raise ValueError("請填入手機使用的 HTTPS 網址，不含路徑。")
    # Access .port to reject malformed/out-of-range ports as well.
    port = parts.port
    host = parts.hostname.lower()
    if ":" in host:
        host = "["+host+"]"
    return "https://" + host + (f":{port}" if port is not None and port != 443 else "")


class RemoteStore:
    """Private device grants and durable operation IDs, separate from profiles."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
                expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                origin TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS operations (
                device TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL,
                action TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL,
                created REAL NOT NULL, PRIMARY KEY(device,id));
        """)
        if 'origin' not in {row[1] for row in self.db.execute('PRAGMA table_info(devices)')}:
            self.db.execute("ALTER TABLE devices ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
        self.db.execute(
            "UPDATE operations SET status='unknown',result=? WHERE status='running'",
            (json.dumps({"message": "電腦程式曾中斷，請核對結果；不會重送。"}),))
        self.db.commit()

    def setting(self, key: str, default="") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))

    def pair(self, name: str, origin: str = '') -> tuple[str, str]:
        if len(self.devices()) >= 12:
            raise ValueError("已配對裝置過多，請先移除不使用的裝置。")
        device, token = secrets.token_hex(12), secrets.token_urlsafe(32)
        with self.db:
            self.db.execute("INSERT INTO devices(id,name,digest,expires,origin) VALUES (?,?,?,?,?)",
                            (device, name[:32], self.digest(token), time.time()+SESSION_SECONDS, origin))
        return device, token

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def authenticate(self, token: str, origin: str | None = None) -> str | None:
        if not token or len(token) > 100:
            return None
        row = self.db.execute(
            "SELECT id,origin FROM devices WHERE digest=? AND revoked=0 AND expires>?",
            (self.digest(token), time.time())).fetchone()
        # A temporary hostname may later belong to somebody else. A cookie
        # from that hostname must never authorize a different/new endpoint.
        if row and origin is not None and row[1] != origin:
            if row[1] or not origin.startswith('http://127.0.0.1:'):
                return None
        return row[0] if row else None

    def authorized(self, device: str) -> bool:
        return self.db.execute("SELECT 1 FROM devices WHERE id=? AND revoked=0 AND expires>?",
                               (device, time.time())).fetchone() is not None

    def devices(self) -> list[dict]:
        return [dict(id=r[0], name=r[1]) for r in self.db.execute(
            "SELECT id,name FROM devices WHERE revoked=0 AND expires>?", (time.time(),))]

    def revoke(self, device: str):
        with self.db:
            self.db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device,))

    def operation(self, device: str, identifier: str) -> dict | None:
        row = self.db.execute(
            "SELECT id,action,status,result,digest FROM operations WHERE device=? AND id=?",
            (device, identifier)).fetchone()
        return dict(id=row[0], action=row[1], status=row[2], result=json.loads(row[3]),
                    digest=row[4]) if row else None

    def begin(self, device: str, identifier: str, action: str, digest: str):
        with self.db:
            self.db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                            (device, identifier, digest, action, "running", "{}", time.time()))
            self.db.execute("DELETE FROM operations WHERE status!='running' AND rowid NOT IN "
                            "(SELECT rowid FROM operations ORDER BY created DESC LIMIT 512)")

    def finish(self, device: str, identifier: str, status: str, result: dict):
        with self.db:
            self.db.execute("UPDATE operations SET status=?,result=? WHERE device=? AND id=?",
                            (status, json.dumps(result, ensure_ascii=False), device, identifier))

    def latest(self, device: str) -> dict | None:
        row = self.db.execute("SELECT id FROM operations WHERE device=? ORDER BY created DESC LIMIT 1",
                              (device,)).fetchone()
        result = self.operation(device, row[0]) if row else None
        if result:
            result.pop("digest", None)
        return result


class MobileServer(QObject):
    command = Signal(str, object)
    changed = Signal()

    def __init__(self, store: RemoteStore, assets: dict, parent=None):
        super().__init__(parent)
        use_windows_native_tls()
        self.store, self.assets = store, assets
        self.http = QTcpServer(self)
        self.websockets = QWebSocketServer("對沖小幫手", QWebSocketServer.NonSecureMode, self)
        self.http.newConnection.connect(self._http_connection)
        self.websockets.newConnection.connect(self._websocket_connection)
        self.websockets.setHandshakeTimeout(5000)
        self.sockets = {}
        self.pending = set()
        self.public_origin = ""
        self.state = {}
        self.ruler_image = b''
        self.revision = 0
        self.lease = ""
        self.lease_until = 0.0
        self.pair_code = ""
        self.pair_until = 0.0
        self.pair_attempts = 0
        self._last_encoded = ""

    @property
    def local_origin(self):
        return f"http://127.0.0.1:{self.http.serverPort()}"

    def start(self, public_origin: str = "", port: int = 8765):
        if self.http.isListening():
            return
        self.public_origin = normalized_origin(public_origin) if public_origin else ""
        if not self.http.listen(QHostAddress.SpecialAddress.LocalHost, port):
            raise ValueError("手機連線入口無法開啟，可能已有其他程式使用此連接埠。")
        self.changed.emit()

    def stop(self):
        self.http.close()
        for sock in list(self.pending):
            sock.abort()
        self.pending.clear()
        for sock in list(self.sockets):
            sock.close()
        self.sockets.clear()
        self.pair_code = ""
        self.pair_until = 0
        self.changed.emit()

    def arm_pairing(self) -> str:
        if not self.http.isListening():
            raise ValueError("請先啟用手機連線。")
        self.pair_code = f"{secrets.randbelow(100_000_000):08d}"
        self.pair_until = time.monotonic()+300
        self.pair_attempts = 0
        return self.pair_code

    def publish(self, state: dict):
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if encoded != self._last_encoded or time.monotonic() >= self.lease_until-5:
            self._last_encoded = encoded
            self.state = state
            self.revision += 1
            self.lease = secrets.token_hex(16)
            self.lease_until = time.monotonic()+30
            for sock, device in list(self.sockets.items()):
                if not self.store.authorized(device):
                    sock.close()
                else:
                    self.send(sock, {"type": "state", "revision": self.revision,
                                     "lease": self.lease, "state": state,
                                     "operation": self.store.latest(device)})

    @staticmethod
    def send(sock, data):
        if sock.state() == QAbstractSocket.SocketState.ConnectedState:
            if sock.bytesToWrite() > 256_000:
                sock.close()
                return
            sock.sendTextMessage(json.dumps(data, ensure_ascii=False, allow_nan=False))

    def reply(self, device: str, data: dict):
        for sock, owner in list(self.sockets.items()):
            if owner == device:
                self.send(sock, data)

    def _http_connection(self):
        while self.http.hasPendingConnections():
            sock = self.http.nextPendingConnection()
            if len(self.pending)+len(self.sockets) >= 12:
                sock.abort()
                sock.deleteLater()
                continue
            self.pending.add(sock)
            sock.setReadBufferSize(32_768)
            sock.readyRead.connect(lambda target=sock: self._http_read(target))
            sock.disconnected.connect(lambda target=sock: self.pending.discard(target))
            sock.disconnected.connect(sock.deleteLater)
            QTimer.singleShot(5000, sock, lambda target=sock: self._expire_http(target))

    def _expire_http(self, sock):
        if sock in self.pending:
            self.pending.discard(sock)
            sock.abort()

    def _allowed_origin(self, host: str) -> str:
        if host == urlsplit(self.local_origin).netloc:
            return self.local_origin
        if self.public_origin and host == urlsplit(self.public_origin).netloc:
            return self.public_origin
        return ""

    @staticmethod
    def _cookie_token(raw: str) -> str:
        jar = SimpleCookie()
        try:
            jar.load(raw)
            return jar[COOKIE].value if COOKIE in jar else ""
        except Exception:
            return ""

    def _http_read(self, sock):
        if sock not in self.pending:
            return
        raw = bytes(sock.peek(32_769))
        end = raw.find(b"\r\n\r\n")
        if end < 0:
            if len(raw) > 16_384:
                self._respond(sock, 400, b"Invalid request")
            return
        try:
            if end > 16_384:
                raise ValueError()
            lines = raw[:end].decode("ascii").split("\r\n")
            method, path, version = lines[0].split(" ")
            headers = {}
            for line in lines[1:]:
                key, value = line.split(":", 1)
                key = key.lower()
                if key in headers or not re.fullmatch(r"[a-z0-9-]+", key):
                    raise ValueError()
                headers[key] = value.strip()
            if version != "HTTP/1.1" or "transfer-encoding" in headers:
                raise ValueError()
            origin = self._allowed_origin(headers.get("host", ""))
            if not origin:
                self._respond(sock, 403, b"Invalid host")
                return
            length = int(headers.get("content-length", "0"))
            if length < 0 or length > 4096:
                raise ValueError()
            if len(raw) < end+4+length:
                return
            if path == "/ws" and method == "GET":
                if headers.get("origin") != origin or headers.get("upgrade", "").lower() != "websocket":
                    self._respond(sock, 403, b"Invalid origin")
                    return
                token = self._cookie_token(headers.get("cookie", ""))
                if not self.store.authenticate(token, origin):
                    self._respond(sock, 401, b"Pairing required")
                    return
                self.pending.discard(sock)
                sock.readyRead.disconnect()
                # QWebSocketServer reads the still-buffered handshake itself.
                self.websockets.handleConnection(sock)
                return
            sock.read(end+4+length)
            if method == "GET" and path == "/api/session" and not length:
                authenticated = self.store.authenticate(self._cookie_token(headers.get("cookie", "")), origin)
                self._respond(sock, 200 if authenticated else 401,
                              b'{"paired":true}' if authenticated else b'{"paired":false}',
                              "application/json")
                return
            if method == 'GET' and re.fullmatch(r'/api/ruler.png\?v=[a-f0-9]{16}', path) and not length:
                authenticated = self.store.authenticate(self._cookie_token(headers.get('cookie', '')), origin)
                self._respond(sock, 200 if authenticated else 401,
                              self.ruler_image if authenticated else b'Pairing required',
                              'image/png' if authenticated else 'text/plain')
                return
            if method == "POST" and path == "/api/pair":
                if (headers.get("origin") != origin
                        or headers.get("content-type", "").split(";")[0] != "application/json"):
                    self._respond(sock, 403, b"Invalid origin")
                    return
                payload = json.loads(raw[end+4:end+4+length])
                if not isinstance(payload, dict):
                    raise ValueError()
                self.pair_attempts += 1
                code = payload.get("code", "")
                if (not isinstance(code, str) or not self.pair_code
                        or self.pair_attempts > 5 or time.monotonic() > self.pair_until
                        or not hmac.compare_digest(code, self.pair_code)):
                    self._respond(sock, 403, "配對碼錯誤或已失效，請在電腦重新產生。".encode())
                    return
                name = payload.get("name", "我的手機")
                if not isinstance(name, str) or len(name) > 32:
                    raise ValueError()
                _, token = self.store.pair(name, origin)
                self.pair_code = ""
                secure = "; Secure" if origin.startswith("https:") else ""
                cookie = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}{secure}"
                self._respond(sock, 200, b'{"paired":true}', "application/json", [f"Set-Cookie: {cookie}"])
                self.changed.emit()
                return
            if method == "GET" and path in self.assets and not length:
                content_type, content = self.assets[path]
                self._respond(sock, 200, content.encode("utf-8") if isinstance(content, str) else content, content_type)
                return
            self._respond(sock, 404, b"Not found")
        except (ValueError, UnicodeError, KeyError, TypeError):
            self._respond(sock, 400, b"Invalid request")
        except (sqlite3.Error, OSError):
            self._respond(sock, 503, "手機連線儲存失敗，請在電腦確認。".encode("utf-8"))

    def _respond(self, sock, status, body, content_type="text/plain; charset=utf-8", extra=()):
        self.pending.discard(sock)
        origins = [self.local_origin] + ([self.public_origin] if self.public_origin else [])
        websocket_sources = " ".join(o.replace("http", "ws", 1) for o in origins)
        headers = [f"HTTP/1.1 {status} Response", f"Content-Type: {content_type}",
                   f"Content-Length: {len(body)}", "Connection: close", "Cache-Control: no-store",
                   "X-Content-Type-Options: nosniff", "X-Frame-Options: DENY",
                   "Referrer-Policy: no-referrer", "Permissions-Policy: camera=(), microphone=(), geolocation=()",
                   "Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; "
                   f"connect-src 'self' {websocket_sources}; img-src 'self'; manifest-src 'self'; "
                   "worker-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"]
        if self.public_origin:
            headers.append("Strict-Transport-Security: max-age=31536000")
        sock.write(("\r\n".join(headers+list(extra))+"\r\n\r\n").encode("ascii")+body)
        sock.disconnectFromHost()

    def _websocket_connection(self):
        while self.websockets.hasPendingConnections():
            sock = self.websockets.nextPendingConnection()
            request = sock.request()
            origin = bytes(request.rawHeader("Origin")).decode("ascii", "ignore")
            host = bytes(request.rawHeader("Host")).decode("ascii", "ignore")
            device = self.store.authenticate(self._cookie_token(
                bytes(request.rawHeader("Cookie")).decode("ascii", "ignore")), self._allowed_origin(host))
            if not device or origin != self._allowed_origin(host) or len(self.sockets) >= 8:
                sock.close()
                sock.deleteLater()
                continue
            self.sockets[sock] = device
            sock._mobile_messages = deque(maxlen=31)
            sock.setMaxAllowedIncomingFrameSize(MAX_MESSAGE)
            sock.setMaxAllowedIncomingMessageSize(MAX_MESSAGE)
            sock.textMessageReceived.connect(lambda raw, target=sock: self._message(target, raw))
            sock.disconnected.connect(lambda target=sock: self.sockets.pop(target, None))
            sock.disconnected.connect(sock.deleteLater)
            self.send(sock, {"type": "state", "revision": self.revision, "lease": self.lease,
                             "state": self.state, "operation": self.store.latest(device)})

    def _message(self, sock, raw):
        device = self.sockets.get(sock)
        if not device or not self.store.authorized(device):
            sock.close()
            return
        try:
            now = time.monotonic()
            sock._mobile_messages.append(now)
            if len(sock._mobile_messages) == 31 and now-sock._mobile_messages[0] < 1:
                sock.close()
                return
            payload = json.loads(raw)
            if not isinstance(payload, dict) or len(raw) > MAX_MESSAGE:
                raise ValueError()
            if payload.get("type") == "ping":
                echo = payload.get("echo", 0)
                self.send(sock, {"type": "pong", "time": time.time(),
                                 "echo": echo if type(echo) is int else 0})
                return
            self.command.emit(device, payload)
        except (ValueError, TypeError):
            self.send(sock, {"type": "error", "message": "無法辨識操作，請重新連線。"})
