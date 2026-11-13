"""Build a Windows ZIP with its own Python; never reads local account data."""
from __future__ import annotations

import argparse
import base64
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile

from packaging.requirements import Requirement

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trading_helper.self_update import managed

ROOT_NAME = "AUTO-TRADING-lab-unified"
LAUNCHER = '''Option Explicit
Dim fso, shell, root, python, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = root & "\\runtime\\pythonw.exe"
If Not fso.FileExists(python) Then
    MsgBox "請先解壓縮完整下載包，再開啟程式。", 48, "對沖小幫手"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
command = Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\\main.py" & Chr(34)
shell.Run command, 1, False
'''
FIRST_RUN = """對沖小幫手 Windows 免安裝版

1. 將整個 ZIP 解壓縮到你有寫入權限的資料夾。
2. 雙擊「啟動對沖小幫手.vbs」。不需另外安裝 Python。
3. 第一次使用：設定自己的試算表，綁定交易視窗並完成校準。

請保留 AUTO-TRADING-lab-unified 資料夾名稱，以便程式自動更新。
程式、runtime 和 vendor 資料夾需放在一起。
你的設定、方案與紀錄存放在 Windows 使用者資料夾，未包含在下載包。
更新後請沿用原本的捷徑與資料夾；一般程式更新會沿用這份 Python 環境。
如果新版需要更換執行環境，更新時會一併下載並安裝獨立環境；啟動失敗會還原舊版。
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_key(source: Path) -> str:
    digest = hashlib.sha256(sys.version.encode())
    digest.update(sysconfig.get_platform().encode())
    for name in ("requirements.txt", "requirements-portable.txt"):
        digest.update((source / name).read_bytes().replace(b"\r\n", b"\n"))
    digest.update(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))
    versions = [(d.metadata["Name"], d.version) for d in installed_distributions(source)]
    digest.update(json.dumps(versions, sort_keys=True).encode())
    return digest.hexdigest()[:24]


def installed_distributions(source: Path) -> list:
    """Resolve only the application's tested dependencies, including extras."""
    pending = [Requirement(line.strip()) for line in
               (source / "requirements.txt").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    found = {}
    expanded = set()
    while pending:
        req = pending.pop()
        if req.marker and not req.marker.evaluate():
            continue
        dist = metadata.distribution(req.name)
        if req.specifier and not req.specifier.contains(dist.version):
            raise RuntimeError(f"建置環境的 {req.name} {dist.version} 不符合 {req.specifier}。")
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"].lower())
        key = (name, tuple(sorted(req.extras)))
        if key in expanded:
            continue
        expanded.add(key)
        found[name] = dist
        for dependency in dist.requires or []:
            dep = Requirement(dependency)
            if dep.marker and not any(dep.marker.evaluate({"extra": extra}) for extra in ("", *req.extras)):
                continue
            dep.marker = None
            pending.append(dep)
    return [found[name] for name in sorted(found)]


def copy_tested_dependencies(source: Path, destination: Path) -> None:
    """Copy wheel RECORD files, excluding scripts, editable links and local URLs."""
    for dist in installed_distributions(source):
        if dist.files is None:
            raise RuntimeError(f"{dist.metadata['Name']} 缺少套件檔案清單。")
        for record in dist.files:
            relative = PurePosixPath(str(record).replace("\\", "/"))
            if (relative.is_absolute() or ".." in relative.parts or ":" in str(relative)
                    or relative.suffix == ".pyc" or "__pycache__" in relative.parts
                    or relative.name == "direct_url.json"):
                continue
            original = Path(dist.locate_file(record))
            if not original.is_file():
                raise RuntimeError(f"建置套件缺少檔案：{record}")
            if record.hash and record.hash.mode == "sha256":
                actual = base64.urlsafe_b64encode(bytes.fromhex(sha256_file(original))).decode().rstrip("=")
                if actual != record.hash.value:
                    raise RuntimeError(f"建置套件曾被修改：{record}")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and sha256_file(target) != sha256_file(original):
                raise RuntimeError(f"套件檔案衝突：{record}")
            shutil.copy2(original, target)


def prepare_runtime(source: Path, cache: Path) -> Path:
    """Reuse a complete cache; install only into our isolated build directory."""
    if os.name != "nt" or sysconfig.get_platform() != "win-amd64":
        raise RuntimeError("下載包需要使用 Windows x64 Python 建置。")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / runtime_key(source)
    if (target / "complete").is_file():
        print("Reusing cached Python and dependencies", flush=True)
        return target
    if target.exists():
        raise RuntimeError("建置快取不完整，請先移開該快取資料夾。")
    stage = Path(tempfile.mkdtemp(prefix="building-", dir=cache))
    runtime = stage / "python"
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for path in base.iterdir():
        if path.is_file() and (path.suffix.lower() in (".dll", ".zip")
                               or path.name in ("python.exe", "pythonw.exe", "LICENSE.txt")):
            shutil.copy2(path, runtime / path.name)
    for name in ("Lib", "DLLs"):
        shutil.copytree(base / name, runtime / name, ignore=shutil.ignore_patterns(
            "site-packages", "__pycache__", "test", "tests", "*.pyc", "sitecustomize.py", "usercustomize.py"))
    if not all((runtime / name).is_file() for name in ("python.exe", "pythonw.exe")):
        raise RuntimeError("Python 安裝缺少執行檔，無法產生免安裝包。")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW}
    copy_tested_dependencies(source, runtime / "Lib" / "site-packages")
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
               "--cache-dir", str(cache / "pip"), "--target", str(stage / "mt5_readonly"),
               "-r", str(source / "requirements-portable.txt"), "--no-deps", "--only-binary=:all:"]
    installed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", timeout=180, **flags)
    if installed.returncode:
        raise RuntimeError(f"無法準備 MT5 唯讀套件：\n{installed.stdout[-6000:]}")
    # The DLL-specific path file isolates Python from registry/PYTHONPATH settings.
    pth = runtime / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth.write_text(".\nLib\nDLLs\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
    (stage / "complete").write_text(sys.version, encoding="utf-8")
    stage.rename(target)
    return target


def application_files(source: Path) -> list[str]:
    tracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"])
    result = []
    for path in tracked.decode("utf-8").split("\0"):
        if path and managed(path):
            if (source / path).is_symlink():
                raise ValueError("下載包不能包含程式檔案連結。")
            result.append(path)
    if not {"main.py", "requirements.txt", "trading_helper/__init__.py"} <= set(result):
        raise ValueError("下載包缺少必要程式檔案。")
    return sorted(result)


def assemble(source: Path, runtime: Path, destination: Path, commit: str) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for path in application_files(source):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / path, target)
        hashes[path] = sha256_file(target)
    shutil.copytree(runtime / "python", destination / "runtime")
    shutil.copytree(runtime / "mt5_readonly", destination / "vendor" / "mt5_readonly")
    (destination / ".lab-update.json").write_text(
        json.dumps({"files": hashes, "commit": commit}), encoding="utf-8")
    (destination / "啟動對沖小幫手.vbs").write_text(LAUNCHER, encoding="utf-16")
    (destination / "開始使用.txt").write_text(FIRST_RUN, encoding="utf-8-sig")


def smoke_test(destination: Path) -> None:
    """Use only the copied interpreter; no configuration or broker connection."""
    program = """
import sys
from pathlib import Path
root = Path.cwd().resolve()
assert Path(sys.prefix).resolve() == root / 'runtime', sys.prefix
from PySide6.QtWidgets import QApplication
from trading_helper.update_ui import UpdateDialog
from trading_helper.update_check import UpdateNotice
from trading_helper.mt5_native_readonly import _sdk
from rapidocr_onnxruntime import RapidOCR
from trading_helper.self_update import baseline
qt = QApplication([])
dialog = UpdateDialog(UpdateNotice('0.0.0', '0.0.1'), None)
dialog.show(); qt.processEvents(); dialog.close()
assert _sdk().__version__
RapidOCR()
assert baseline(root)
print('Portable imports, Qt, OCR models, MT5 import and updater receipt OK')
"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    subprocess.run([str(destination / "runtime" / "python.exe"), "-I", "-c", program],
                   cwd=destination, env=env, check=True, timeout=120,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def archive_package(destination: Path, output: Path, version: str, commit: str) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("版本或提交編號不正確。")
    asset = f"AUTO-TRADING-Windows-x64-v{version}-{commit[:8]}.zip"
    zip_path = output / asset
    with zip_path.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for path in sorted(destination.rglob("*")):
                if path.is_symlink():
                    raise ValueError("下載包內含連結，已停止。")
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, ROOT_NAME + "/" + path.relative_to(destination).as_posix())
    checksum = sha256_file(zip_path)
    (output / (asset + ".sha256")).write_text(f"{checksum}  {asset}\n", encoding="ascii")
    metadata = {"version": version, "commit": commit, "asset": asset, "sha256": checksum,
                "tag": f"lab-v{version}-{commit[:8]}", "python": sys.version.split()[0]}
    (output / "release-info.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (output / "RELEASE_NOTES.md").write_text(
        f"Windows x64 免安裝包 v{version}\n\n"
        "下載 ZIP 並完整解壓縮，雙擊「啟動對沖小幫手.vbs」。不需另外安裝 Python。\n\n"
        "首次使用仍需設定自己的試算表、綁定交易視窗及校準。下載包不包含個人帳戶資料。\n\n"
        f"來源：`{commit}`\nSHA-256：`{checksum}`\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--cache", type=Path, default=Path(".portable-runtime"))
    parser.add_argument("--cache-key", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    if args.cache_key:
        print(runtime_key(source))
        return
    args.output = args.output.resolve()
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"]).decode().strip()
    subprocess.run(["git", "-C", str(source), "diff", "--exit-code", "HEAD", "--",
                    "main.py", "requirements.txt", "trading_helper", "assets"], check=True)
    version_source = (source / "trading_helper/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)', version_source, re.M)
    if match is None:
        raise ValueError("找不到程式版本。")
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = prepare_runtime(source, args.cache.resolve())
    staging = Path(tempfile.mkdtemp(prefix="portable-", dir=args.output)) / ROOT_NAME
    assemble(source, runtime, staging, commit)
    smoke_test(staging)
    result = archive_package(staging, args.output, match.group(1), commit)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
