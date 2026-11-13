"""Release environment upgrades use fake archives/network, never pip or brokers."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from trading_helper import portable_environment as env


class PortableEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.source={"main.py":b"print('version')\n","requirements.txt":b"PySide6\n"}
        self.package=self.root/"download.zip"
        self.entries={**self.source,"runtime/pythonw.exe":b"pythonw",
            "runtime/python.exe":b"python","runtime/python311._pth":b".\nLib\nLib/site-packages\n..\nimport site\n",
            "vendor/mt5_readonly/MetaTrader5/sdk.pyd":b"sdk",
            "config.json":b"must not install","google-service-account.json":b"secret"}

    def archive(self):
        with zipfile.ZipFile(self.package,"w") as archive:
            for name,data in self.entries.items():
                info=zipfile.ZipInfo("AUTO-TRADING-lab-unified/placeholder")
                # ZipInfo normally normalizes '\\' on Windows. Model a
                # hostile archive arriving from elsewhere without that fix.
                info.filename="AUTO-TRADING-lab-unified/"+name
                archive.writestr(info,data)

    def test_verified_archive_isolates_runtime_and_does_not_extract_user_files(self):
        self.archive()
        destination=self.root/"environment"
        hashes=env.extract_environment(self.package,destination,self.source)
        self.assertEqual(set(hashes),{
            "python/python.exe","python/pythonw.exe","python/python311._pth",
            "mt5_readonly/MetaTrader5/sdk.pyd"})
        self.assertIn("../..",(destination/"python/python311._pth").read_text())
        self.assertFalse((destination/"config.json").exists())
        self.assertFalse((destination/"google-service-account.json").exists())
        for path,checksum in hashes.items():
            self.assertEqual(hashlib.sha256((destination/path).read_bytes()).hexdigest(),checksum)

    def test_release_source_must_match_pinned_git_source(self):
        self.entries["main.py"]=b"different version"
        self.archive()
        with self.assertRaisesRegex(ValueError,"指定版本不同"):
            env.extract_environment(self.package,self.root/"new",self.source)

    def test_windows_checkout_line_endings_match_same_git_source(self):
        self.entries["main.py"]=self.source["main.py"].replace(b"\n",b"\r\n")
        self.archive()
        self.assertTrue(env.extract_environment(self.package,self.root/"new",self.source))

    def test_symbolic_links_in_runtime_are_rejected(self):
        self.archive()
        with zipfile.ZipFile(self.package,"a") as archive:
            info=zipfile.ZipInfo("AUTO-TRADING-lab-unified/runtime/escape")
            info.create_system=3
            info.external_attr=0o120777<<16
            archive.writestr(info,"../../outside")
        with self.assertRaisesRegex(ValueError,"位置"):
            env.extract_environment(self.package,self.root/"new",self.source)

    def test_paths_and_symlinks_are_rejected(self):
        for name in ("../../outside","runtime/../outside","runtime/C:/outside","runtime/a\\b"):
            with self.subTest(name=name):
                self.entries[name]=b"escape"
                self.archive()
                with self.assertRaisesRegex(ValueError,"位置"):
                    env.extract_environment(self.package,self.root/"new",self.source)
                del self.entries[name]

    def test_package_download_checks_streamed_hash_and_allowed_redirect(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return "https://release-assets.githubusercontent.com/file"
            def read(self,size):
                data=self.data
                self.data=b""
                return data
        response=Response()
        response.data=b"package bytes"
        with patch.object(env,"urlopen",return_value=response):
            env.download_package(f"https://github.com/{env.REPOSITORY}/releases/download/tag/file.zip",
                                 self.package,hashlib.sha256(response.data).hexdigest())
        response.data=b"tampered"
        with patch.object(env,"urlopen",return_value=response):
            with self.assertRaisesRegex(ValueError,"完整性"):
                env.download_package(f"https://github.com/{env.REPOSITORY}/releases/download/tag/file.zip",
                                     self.package,"a"*64)
        with self.assertRaisesRegex(ValueError,"來源"):
            env.download_package("https://other.example/file",self.package,"a"*64)

    def test_release_must_match_exact_commit_version_and_checksum(self):
        commit="a"*40
        tag="lab-v1.2.3-aaaaaaaa"
        name="AUTO-TRADING-Windows-x64-v1.2.3-aaaaaaaa.zip"
        prefix=f"https://github.com/{env.REPOSITORY}/releases/download/{tag}/"
        release={"tag_name":tag,"target_commitish":commit,"assets":[
            {"name":"release-info.json","browser_download_url":prefix+"release-info.json"},
            {"name":name,"browser_download_url":prefix+name,"size":50,"digest":"sha256:"+"b"*64}]}
        manifest={"commit":commit,"tag":tag,"version":"1.2.3","asset":name,"sha256":"b"*64}
        self.archive()
        def download(url,target,checksum):
            self.assertEqual(url,prefix+name)
            self.assertEqual(checksum,"b"*64)
        with patch.object(env,"read_download",side_effect=[json.dumps([release]).encode(),json.dumps(manifest).encode()]), \
             patch.object(env,"download_package",side_effect=download), \
             patch.object(env,"extract_environment",return_value={"python/pythonw.exe":"hash"}) as extract:
            # The branch advanced by docs only; release source is still
            # checked against ALL pinned files by extract_environment.
            result=env.prepare_environment(self.root,"f"*40,"1.2.3",self.source)
        self.assertRegex(result["path"],r"^\.hedge-runtime-[a-f0-9]{32}$")
        extract.assert_called_once_with(self.root/"package.zip",self.root/"environment",self.source)
        release["target_commitish"]="c"*40
        with patch.object(env,"read_download",return_value=json.dumps([release]).encode()):
            with self.assertRaisesRegex(ValueError,"指定版本"):
                env.prepare_environment(self.root,commit,"1.2.3",self.source)
