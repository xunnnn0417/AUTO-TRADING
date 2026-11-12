"""Pinned GitHub LAB downloads and a standalone, reversible update worker."""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import zipfile

REPOSITORY = "xunnnn0417/AUTO-TRADING"
BRANCH = "lab/2026-10-16-safe-defaults-preflight"
MAX_DOWNLOAD = 25 * 1024 * 1024
RECEIPT = ".lab-update.json"


def managed(path: str) -> bool:
    p = PurePosixPath(path)
    return bool(
        bool(p.parts) and not p.is_absolute() and ".." not in p.parts and "\\" not in path
        and ":" not in path
        and (path in ("main.py", "requirements.txt")
             or (p.parts[0] == "trading_helper" and p.suffix == ".py")
             or (p.parts[0] == "assets" and p.suffix in (".ico", ".png", ".svg")))
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_download(url: str) -> bytes:
    if urlsplit(url).hostname not in ("api.github.com", "codeload.github.com"):
        raise ValueError("更新來源不正確。")
    req = Request(url, headers={"User-Agent": "HedgeAssistant-LAB-updater"})
    with urlopen(req, timeout=15) as response:
        if urlsplit(response.geturl()).hostname not in ("api.github.com", "codeload.github.com"):
            raise ValueError("更新下載被導向其他網站。")
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("更新檔案過大，請改用 GitHub 更新頁。")
    return data


def require_lab(root: Path) -> Path:
    root = root.resolve()
    if root.name.lower() not in ("auto-trading-lab-unified", "auto-trading-lab"):
        raise ValueError("自動更新只適用 LAB 安裝資料夾。")
    return root


def checked_path(root: Path, path: str) -> Path:
    target = root / path
    if not managed(path) or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("更新檔案位置不正確。")
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("更新資料夾含連結，已停止更新。")
    return target


def baseline(root: Path) -> dict[str, str]:
    """Recognize an earlier installed update, or an unmodified Git checkout."""
    receipt = root / RECEIPT
    if receipt.exists():
        files = json.loads(receipt.read_text(encoding="utf-8"))["files"]
    else:
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        top = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], **flags)
        if Path(top.decode().strip()).resolve() != root:
            raise ValueError("找不到此 LAB 的原始版本，請使用 GitHub 更新頁。")
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all",
             "--", "main.py", "requirements.txt", "trading_helper", "assets"], **flags)
        if dirty.strip():
            raise ValueError("本機程式有尚未保存的修改，請先處理後再更新。設定與校準不受影響。")
        tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"], **flags)
        files = {p: digest(checked_path(root, p).read_bytes())
                 for p in tracked.decode("utf-8").split("\0") if p and managed(p)}
    for path, expected in files.items():
        target = checked_path(root, path)
        if not target.is_file() or digest(target.read_bytes()) != expected:
            raise ValueError("本機程式曾被修改，已保留原檔；請先處理修改後再更新。")
    extras = [p.relative_to(root).as_posix() for folder in ("trading_helper", "assets")
              for p in (root / folder).rglob("*") if p.is_file()]
    if any(managed(p) and p not in files for p in extras):
        raise ValueError("LAB 有額外的程式檔案，請先處理後再更新。")
    return files


def prepare_update(root: Path, current_version: str) -> Path:
    from trading_helper.update_check import _VERSION_LINE, _version_tuple

    root = require_lab(root)
    before = baseline(root)
    api = f"https://api.github.com/repos/{REPOSITORY}"
    commit = json.loads(read_download(f"{api}/commits/{quote(BRANCH, safe='')}"))
    sha = commit["sha"]
    tree_sha = commit["commit"]["tree"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
        raise ValueError("GitHub 版本資料不完整。")
    tree = json.loads(read_download(f"{api}/git/trees/{tree_sha}?recursive=1"))
    if tree.get("truncated"):
        raise ValueError("GitHub 檔案清單不完整。")
    expected = {x["path"]: x["sha"] for x in tree["tree"]
                if managed(x["path"]) and x["type"] == "blob" and x["mode"] == "100644"}
    files = {}
    with zipfile.ZipFile(io.BytesIO(read_download(f"https://codeload.github.com/{REPOSITORY}/zip/{sha}"))) as archive:
        if len(archive.infolist()) > 3000 or sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError("更新壓縮檔超出限制。")
        for info in archive.infolist():
            path = info.filename.partition("/")[2]
            if info.is_dir() or not managed(path):
                continue
            data = archive.read(info)
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if path in files or expected.get(path) != blob or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("更新檔案核對失敗，已保留原版本。")
            if path.endswith(".py"):
                compile(data, path, "exec")
            files[path] = data
    if set(files) != set(expected) or not {"main.py", "trading_helper/__init__.py", "requirements.txt"} <= files.keys():
        raise ValueError("更新缺少必要檔案。")
    version = _VERSION_LINE.search(files["trading_helper/__init__.py"].decode("utf-8-sig"))
    latest = _version_tuple(version.group(1)) if version else None
    current = _version_tuple(current_version)
    if latest is None or current is None or latest <= current:
        raise ValueError("目前已是最新版，無須更新。")
    if files["requirements.txt"].replace(b"\r\n", b"\n").strip() != (root / "requirements.txt").read_bytes().replace(b"\r\n", b"\n").strip():
        raise ValueError("此版本需要更新執行環境，請使用 GitHub 更新頁；目前版本已保留。")
    parent = root.parent / ".hedge-updates"
    parent.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="update-", dir=parent))
    after = {}
    for path, data in files.items():
        target = checked_path(stage / "new", path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        after[path] = digest(data)
    (stage / "plan.json").write_text(json.dumps({
        "root": str(root), "before": before, "after": after,
        "commit": sha, "version": version.group(1),
    }), encoding="utf-8")
    shutil.copyfile(__file__, stage / "worker.py")
    return stage


def replace_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".hedge-update-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def apply_update(stage: Path) -> dict:
    plan = json.loads((stage / "plan.json").read_text(encoding="utf-8"))
    root = require_lab(Path(plan["root"]))
    if baseline(root) != plan["before"]:
        raise ValueError("下載期間程式有變動，已取消更新。")
    paths = set(plan["before"]) | set(plan["after"])
    # Check every source and destination before touching the installed version.
    for path in paths:
        target = checked_path(root, path)
        if path in plan["before"]:
            if digest(target.read_bytes()) != plan["before"][path]:
                raise ValueError("下載期間程式檔案有變動，已取消更新。")
        elif target.exists():
            raise ValueError("新程式檔案與本機檔案衝突，已取消更新。")
        if path in plan["after"] and digest(checked_path(stage / "new", path).read_bytes()) != plan["after"][path]:
            raise ValueError("下載檔案已變動，已取消更新。")
    backup = stage / "backup"
    for path in plan["before"]:
        dest = checked_path(backup, path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / path, dest)
    if (root / RECEIPT).exists():
        shutil.copyfile(root / RECEIPT, stage / "old-receipt.json")
    try:
        for path in sorted(paths):
            if path in plan["after"]:
                replace_bytes(root / path, (stage / "new" / path).read_bytes())
            else:
                (root / path).unlink()
        replace_bytes(root / RECEIPT, json.dumps({"files": plan["after"], "commit": plan["commit"]}).encode())
    except Exception:
        rollback(stage, plan)
        raise
    return plan


def rollback(stage: Path, plan: dict) -> None:
    root = require_lab(Path(plan["root"]))
    for path in set(plan["before"]) | set(plan["after"]):
        checked_path(root, path)
        if path in plan["before"]:
            replace_bytes(root / path, (stage / "backup" / path).read_bytes())
        else:
            (root / path).unlink(missing_ok=True)
    old = stage / "old-receipt.json"
    if old.exists():
        replace_bytes(root / RECEIPT, old.read_bytes())
    else:
        (root / RECEIPT).unlink(missing_ok=True)


def start_worker(stage: Path, python: str, pid: int) -> None:
    subprocess.Popen([python, str(stage / "worker.py"), str(stage), python, str(pid)],
                     cwd=stage, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def wait_for_exit(pid: int) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # The parent already exited.
            return
        raise OSError("無法確認舊程式已結束，已停止更新。")
    try:
        if kernel.WaitForSingleObject(handle, 30_000) != 0:
            raise TimeoutError("舊程式尚未退出，已停止更新。")
    finally:
        kernel.CloseHandle(handle)


def run_worker(stage: Path, python: str, pid: int) -> None:
    wait_for_exit(pid)
    plan = json.loads((stage / "plan.json").read_text(encoding="utf-8"))
    root = require_lab(Path(plan["root"]))
    process = None
    applied = False
    env = os.environ.copy()
    env.pop("HEDGE_UPDATE_RECEIPT", None)
    try:
        apply_update(stage)
        applied = True
        env["HEDGE_UPDATE_RECEIPT"] = str(stage / "started")
        (stage / "started").unlink(missing_ok=True)
        process = subprocess.Popen([python, str(root / "main.py")], cwd=root, env=env)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if (stage / "started").exists() and process.poll() is None:
                return
            if process.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError("新版啟動失敗，已還原原版本。")
    except Exception as exc:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if applied:
            rollback(stage, plan)
        (stage / "error.txt").write_text(str(exc), encoding="utf-8")
        env.pop("HEDGE_UPDATE_RECEIPT", None)
        env["HEDGE_UPDATE_ERROR"] = str(stage / "error.txt")
        subprocess.Popen([python, str(root / "main.py")], cwd=root, env=env)


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]))
