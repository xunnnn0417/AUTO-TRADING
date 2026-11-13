import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_portable as build
from trading_helper.self_update import baseline


class PortableReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.source = self.home / "source"
        self.source.mkdir()
        self.paths = ["main.py", "requirements.txt", "requirements-portable.txt", "trading_helper/__init__.py", "assets/app.ico"]
        for path in self.paths:
            target = self.source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"code\n")
        (self.source / "requirements-portable.txt").write_text("MetaTrader5==5.0.6231\n")
        (self.source / "requirements.txt").write_text("packaging>=24\n")
        (self.source / "google-service-account.json").write_text("secret-key")
        (self.source / "config.json").write_text("personal sheet and calibration")
        (self.source / "journal.json").write_text("trades")
        self.runtime = self.home / "cache"
        (self.runtime / "python").mkdir(parents=True)
        (self.runtime / "python/python.exe").write_bytes(b"python")
        (self.runtime / "python/pythonw.exe").write_bytes(b"pythonw")
        (self.runtime / "mt5_readonly").mkdir()
        (self.runtime / "mt5_readonly/MetaTrader5.pyd").write_bytes(b"sdk")
        self.commit = "a" * 40
        self.destination = self.home / build.ROOT_NAME

    def assemble(self):
        # Even accidentally tracked personal data must not enter the package.
        tracked = self.paths + ["google-service-account.json", "config.json", "journal.json", "tests/test_user.py"]
        with patch.object(build.subprocess, "check_output", return_value="\0".join(tracked).encode()):
            build.assemble(self.source, self.runtime, self.destination, self.commit)

    def test_first_download_contains_runtime_and_launcher_but_no_user_data(self):
        self.assemble()
        output = self.home / "dist"
        output.mkdir()
        result = build.archive_package(self.destination, output, "1.2.3", self.commit)
        archive_path = output / result["asset"]
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            prefix = build.ROOT_NAME + "/"
            self.assertIn(prefix + "runtime/pythonw.exe", names)
            self.assertIn(prefix + "啟動對沖小幫手.vbs", names)
            self.assertIn(prefix + "vendor/mt5_readonly/MetaTrader5.pyd", names)
            self.assertFalse(any("service-account" in n or n.endswith(("config.json", "journal.json")) for n in names))
            launcher = archive.read(prefix + "啟動對沖小幫手.vbs").decode("utf-16")
            self.assertIn('shell.Run command, 1, False', launcher)
            self.assertNotIn(str(self.source), launcher)
        self.assertEqual(result["sha256"], hashlib.sha256(archive_path.read_bytes()).hexdigest())
        self.assertEqual(json.loads((output / "release-info.json").read_text())["commit"], self.commit)

    def test_portable_first_install_can_use_updater_without_git(self):
        self.assemble()
        expected = json.loads((self.destination / ".lab-update.json").read_text())["files"]
        self.assertEqual(baseline(self.destination), expected)

    def test_missing_required_app_files_prevents_packaging(self):
        with patch.object(build.subprocess, "check_output", return_value=b"main.py\0"):
            with self.assertRaisesRegex(ValueError, "必要程式"):
                build.application_files(self.source)

    def test_new_dependency_environment_has_a_different_cache_key(self):
        first = build.runtime_key(self.source)
        with (self.source / "requirements-portable.txt").open("a") as stream:
            stream.write("# updated dependency environment\n")
        self.assertNotEqual(first, build.runtime_key(self.source))

    def test_complete_runtime_cache_avoids_reinstallation(self):
        cache = self.home / "runtime-cache"
        target = cache / build.runtime_key(self.source)
        target.mkdir(parents=True)
        (target / "complete").write_text("ready")
        with patch.object(build.sysconfig, "get_platform", return_value="win-amd64"), patch.object(build.subprocess, "run") as install:
            # All CI and production packaging runs are Windows x64.
            expected = cache / build.runtime_key(self.source)
            if expected != target:
                target.rename(expected)
                target = expected
            self.assertEqual(build.prepare_runtime(self.source, cache), target)
        install.assert_not_called()

    def test_bad_release_version_does_not_create_an_archive(self):
        with self.assertRaises(ValueError):
            build.archive_package(self.destination, self.home, "../escape", self.commit)
        self.assertFalse(list(self.home.glob("*.zip")))

    def test_smoke_uses_only_packaged_python_and_never_connects_to_mt5(self):
        with patch.object(build.subprocess, "run") as run:
            build.smoke_test(self.home)
        args = run.call_args.args[0]
        self.assertEqual(args[0], str(self.home / "runtime/python.exe"))
        self.assertIn("_sdk()", args[-1])
        for operation in ("initialize(", "order_send(", "positions_get("):
            self.assertNotIn(operation, args[-1])

    def test_dependency_resolution_includes_requested_extras_but_not_unrelated_packages(self):
        (self.source / "requirements.txt").write_text("demo[feature]==1\n")
        distributions = {
            "demo": SimpleNamespace(metadata={"Name": "demo"}, version="1", requires=[
                "child; extra == 'feature'", "other; sys_platform == 'unavailable'"]),
            "child": SimpleNamespace(metadata={"Name": "child"}, version="2", requires=[]),
        }
        with patch.object(build.metadata, "distribution", side_effect=distributions.__getitem__):
            self.assertEqual([d.metadata["Name"] for d in build.installed_distributions(self.source)], ["child", "demo"])
            distributions["demo"].version = "3"
            with self.assertRaisesRegex(RuntimeError, "不符合"):
                build.installed_distributions(self.source)

    def test_copy_tested_wheel_files_excludes_machine_paths_and_detects_tampering(self):
        class Record:
            def __init__(self, path, file_hash=None):
                self.path, self.hash = path, file_hash
            def __str__(self):
                return self.path
        data = b"tested module\n"
        (self.source / "module.py").write_bytes(data)
        value = build.base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        record = Record("module.py", SimpleNamespace(mode="sha256", value=value))
        dist = SimpleNamespace(
            metadata={"Name": "demo"},
            files=[record, Record("../outside.key"), Record("demo.dist-info/direct_url.json")],
            locate_file=lambda p: self.source / str(p),
        )
        destination = self.home / "installed"
        with patch.object(build, "installed_distributions", return_value=[dist]):
            build.copy_tested_dependencies(self.source, destination)
            self.assertEqual((destination / "module.py").read_bytes(), data)
            self.assertFalse((destination / "demo.dist-info/direct_url.json").exists())
            (self.source / "module.py").write_bytes(b"edited")
            with self.assertRaisesRegex(RuntimeError, "曾被修改"):
                build.copy_tested_dependencies(self.source, destination)
