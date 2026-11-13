"""Stage a verified release runtime without changing any running Python."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid
import zipfile

from .self_update import REPOSITORY, digest, read_download

MAX_PACKAGE = 800 * 1024 * 1024


def download_package(url: str, target: Path, expected: str) -> None:
    prefix=f"https://github.com/{REPOSITORY}/releases/download/"
    if not url.startswith(prefix) or not re.fullmatch(r"[a-f0-9]{64}",expected):
        raise ValueError("下載包來源或核對碼不正確。")
    request=Request(url,headers={"User-Agent":"HedgeAssistant-LAB-updater"})
    checksum=hashlib.sha256()
    size=0
    with urlopen(request,timeout=30) as response, target.open("wb") as output:
        if urlsplit(response.geturl()).hostname not in (
            "github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"
        ):
            raise ValueError("下載包被導向不支援的網站。")
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>MAX_PACKAGE:
                raise ValueError("下載包超出大小限制，原版本已保留。")
            output.write(chunk)
            checksum.update(chunk)
    if checksum.hexdigest()!=expected:
        raise ValueError("下載包完整性核對失敗，原版本已保留。")


def extract_environment(package: Path, destination: Path, source_files: dict) -> dict:
    """Extract only a package's runtime/SDK; compare its source to pinned Git."""
    hashes={}
    seen=set()
    matched=set()
    prefix="AUTO-TRADING-lab-unified/"
    with zipfile.ZipFile(package) as archive:
        entries=archive.infolist()
        if len(entries)>40000 or sum(i.file_size for i in entries)>2*1024**3:
            raise ValueError("下載包解壓縮大小不正確。")
        for info in entries:
            if info.is_dir():
                continue
            path=info.filename
            parts=PurePosixPath(path)
            if (not path.startswith(prefix) or ".." in parts.parts
                    or "\\" in info.orig_filename or "\x00" in info.orig_filename
                    or "\\" in path or ":" in path
                    or (info.external_attr>>16)&0o170000==0o120000
                    or path in seen):
                raise ValueError("下載包包含不正確的檔案位置。")
            seen.add(path)
            relative=path[len(prefix):]
            if relative in source_files:
                actual=archive.read(info)
                expected=source_files[relative]
                # GitHub's Windows checkout can use CRLF while codeload
                # serves Git's LF bytes. Only that text normalization differs.
                if relative.endswith(".py") or relative.startswith("requirements"):
                    actual=actual.replace(b"\r\n",b"\n")
                    expected=expected.replace(b"\r\n",b"\n")
                if actual!=expected:
                    raise ValueError("下載包與 GitHub 指定版本不同。")
                matched.add(relative)
            if relative.startswith("runtime/"):
                output="python/"+relative[len("runtime/"):]
            elif relative.startswith("vendor/mt5_readonly/"):
                output="mt5_readonly/"+relative[len("vendor/mt5_readonly/"):]
            else:
                continue
            data=archive.read(info)
            if re.fullmatch(r"python/python\d+\._pth",output):
                # This runtime lives two levels below the application root.
                lines=data.decode("utf-8-sig").splitlines()
                if ".." not in lines:
                    raise ValueError("下載包的 Python 路徑設定不正確。")
                data=("\n".join("../.." if line==".." else line for line in lines)+"\n").encode()
            target=destination/output
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
            hashes[output]=digest(data)
    if (matched!=set(source_files)
            or not {"python/python.exe","python/pythonw.exe"}<=hashes.keys()
            or not any(p.startswith("mt5_readonly/MetaTrader5/") for p in hashes)
            or not any(re.fullmatch(r"python/python\d+\._pth",p) for p in hashes)):
        raise ValueError("下載包缺少必要的程式或執行環境。")
    return hashes


def prepare_environment(stage: Path, commit: str, version: str, files: dict) -> dict:
    api=f"https://api.github.com/repos/{REPOSITORY}"
    try:
        releases=json.loads(read_download(f"{api}/releases?per_page=30"))
    except Exception as exc:
        raise ValueError("新版完整包尚未發布完成，請稍後再按更新；原版本已保留。") from exc
    # A later Markdown-only commit intentionally does not rebuild the ZIP.
    # Select this version's release, then require EVERY managed source file
    # in its archive to match the currently pinned branch source below.
    releases.sort(key=lambda item:item.get("target_commitish")!=commit)
    release=next((item for item in releases if not item.get("draft")
        and re.fullmatch(r"[a-f0-9]{40}",str(item.get("target_commitish","")))
        and item.get("tag_name")==f"lab-v{version}-{item['target_commitish'][:8]}"),None)
    if release is None:
        raise ValueError("下載包尚未對應到指定版本，請稍後再試。")
    release_commit=release["target_commitish"]
    tag=release["tag_name"]
    assets={item["name"]:item for item in release["assets"]}
    manifest_asset=assets.get("release-info.json",{})
    manifest_url=manifest_asset.get("browser_download_url","")
    prefix=f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    if not manifest_url.startswith(prefix):
        raise ValueError("下載包資訊不完整，原版本已保留。")
    manifest=json.loads(read_download(manifest_url))
    if (manifest.get("commit")!=release_commit or manifest.get("version")!=version
            or manifest.get("tag")!=tag):
        raise ValueError("下載包版本核對失敗。")
    name=manifest.get("asset","")
    asset=assets.get(name,{})
    checksum=manifest.get("sha256","")
    if (not re.fullmatch(r"AUTO-TRADING-Windows-x64-v[\d.]+-[a-f0-9]{8}\.zip",name)
            or asset.get("size",MAX_PACKAGE+1)>MAX_PACKAGE
            or asset.get("digest") not in (None,"",f"sha256:{checksum}")):
        raise ValueError("下載包核對碼或格式不正確。")
    package=stage/"package.zip"
    download_package(asset.get("browser_download_url",""),package,checksum)
    hashes=extract_environment(package,stage/"environment",files)
    return {"path":".hedge-runtime-"+uuid.uuid4().hex,"files":hashes}
