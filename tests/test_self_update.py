import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from trading_helper import self_update as update


class SelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "AUTO-TRADING-lab-unified"
        self.root.mkdir()
        # Hosted Windows TEMP may use RUNNER~1 while the updater resolves
        # runneradmin. Keep fault injection and expected launch paths equal
        # to the canonical directory used by the actual updater.
        self.root = self.root.resolve()
        self.files = {
            "main.py": b"print('new')\n",
            "requirements.txt": b"PySide6==6.10.1\n",
            "trading_helper/__init__.py": b'__version__ = "1.0.1"\n',
        }
        self.before = {}
        for path in self.files:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            data = b"print('old')\n" if path == "main.py" else self.files[path]
            target.write_bytes(data)
            self.before[path] = update.digest(data)
        (self.root / update.RECEIPT).write_text(json.dumps({"files": self.before}))
        (self.root / "config.json").write_text("private calibration")
        (self.root / "journal.json").write_text("trade history")

    def download(self, *, corrupt=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for path, data in self.files.items():
                archive.writestr("repo/" + path, b"wrong" if corrupt and path == "main.py" else data)
            archive.writestr("repo/config.json", "must not install")
            archive.writestr("repo/../../outside.txt", "must not extract")
        tree = {"tree": [{"path": path, "type": "blob", "mode": "100644", "sha":
                hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
                for path, data in self.files.items()], "truncated": False}
        return [json.dumps({"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}).encode(),
                json.dumps(tree).encode(), stream.getvalue()]

    def prepare(self):
        with patch.object(update, "read_download", side_effect=self.download()):
            return update.prepare_update(self.root, "1.0.0")

    def test_verified_update_installs_code_and_preserves_user_files(self):
        stage = self.prepare()
        plan = update.apply_update(stage)
        self.assertEqual((self.root / "main.py").read_bytes(), self.files["main.py"])
        self.assertEqual((self.root / "config.json").read_text(), "private calibration")
        self.assertEqual((self.root / "journal.json").read_text(), "trade history")
        self.assertFalse((self.root.parent / "outside.txt").exists())
        self.assertEqual(update.baseline(self.root), plan["after"])

    def test_bad_archive_hash_does_not_change_install(self):
        with patch.object(update, "read_download", side_effect=self.download(corrupt=True)):
            with self.assertRaisesRegex(ValueError, "核對失敗"):
                update.prepare_update(self.root, "1.0.0")
        self.assertEqual((self.root / "main.py").read_bytes(), b"print('old')\n")

    def test_local_modified_code_is_preserved(self):
        (self.root / "main.py").write_bytes(b"local edits")
        with self.assertRaisesRegex(ValueError, "曾被修改"):
            update.baseline(self.root)

    def test_changes_after_download_prevent_apply(self):
        stage = self.prepare()
        (self.root / "main.py").write_bytes(b"later edit")
        with self.assertRaisesRegex(ValueError, "修改"):
            update.apply_update(stage)
        self.assertEqual((self.root / "main.py").read_bytes(), b"later edit")

    def test_staged_tampering_prevents_apply(self):
        stage = self.prepare()
        (stage / "new/main.py").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "下載檔案已變動"):
            update.apply_update(stage)

    def test_write_failure_rolls_back_all_replaced_files(self):
        stage = self.prepare()
        original = update.replace_bytes
        def failing(path, data):
            if path == self.root / "requirements.txt" and data == self.files["requirements.txt"]:
                # Fail once so restoring the original remains possible.
                self.files["requirements.txt"] = b"changed sentinel"
                raise OSError("disk error")
            original(path, data)
        with patch.object(update, "replace_bytes", side_effect=failing):
            with self.assertRaises(OSError):
                update.apply_update(stage)
        self.assertEqual((self.root / "main.py").read_bytes(), b"print('old')\n")
        self.assertEqual(update.baseline(self.root), self.before)

    def test_dependency_change_stages_a_private_runtime_without_touching_shared_python(self):
        self.files["requirements.txt"] = b"new-package==2\n"
        env={"path":".hedge-runtime-"+"c"*32,"files":{}}
        with patch.object(update,"read_download",side_effect=self.download()), patch(
            "trading_helper.portable_environment.prepare_environment",return_value=env
        ) as prepare:
            stage=update.prepare_update(self.root,"1.0.0")
        self.assertEqual(json.loads((stage/"plan.json").read_text())["environment"],env)
        prepare.assert_called_once_with(stage,"a"*40,"1.0.1",self.files)
        self.assertEqual((self.root/"main.py").read_bytes(),b"print('old')\n")

    def test_portable_sdk_dependency_change_keeps_old_environment(self):
        target = self.root / "requirements-portable.txt"
        target.write_bytes(b"MetaTrader5==1\n")
        self.before["requirements-portable.txt"] = update.digest(target.read_bytes())
        (self.root / update.RECEIPT).write_text(json.dumps({"files": self.before}))
        self.files["requirements-portable.txt"] = b"MetaTrader5==2\n"
        with patch.object(update, "read_download", side_effect=self.download()), patch(
            "trading_helper.portable_environment.prepare_environment",
            side_effect=ValueError("執行環境完整包尚未發布"),
        ):
            with self.assertRaisesRegex(ValueError, "執行環境"):
                update.prepare_update(self.root, "1.0.0")
        self.assertEqual(target.read_bytes(), b"MetaTrader5==1\n")

    def make_environment_plan(self):
        stage=self.prepare()
        env=stage/"environment"
        hashes={}
        for name,data in (("python/python.exe",b"new-python"),
                          ("python/pythonw.exe",b"new-pythonw"),
                          ("mt5_readonly/MetaTrader5/sdk.pyd",b"sdk")):
            target=env/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
            hashes[name]=update.digest(data)
        plan=json.loads((stage/"plan.json").read_text())
        plan["environment"]={"path":".hedge-runtime-"+"c"*32,"files":hashes}
        (stage/"plan.json").write_text(json.dumps(plan))
        return stage,plan

    def test_environment_apply_and_rollback_preserve_original_python_and_user_data(self):
        legacy=self.root/"runtime/pythonw.exe"
        legacy.parent.mkdir()
        legacy.write_bytes(b"old-python")
        stage,plan=self.make_environment_plan()
        update.apply_update(stage)
        selected=update.installed_python(self.root)
        self.assertEqual(selected.read_bytes(),b"new-pythonw")
        self.assertEqual(legacy.read_bytes(),b"old-python")
        update.rollback(stage,plan)
        self.assertIsNone(update.installed_python(self.root))
        self.assertEqual((self.root/"config.json").read_text(),"private calibration")
        self.assertEqual((self.root/"journal.json").read_text(),"trade history")

    def test_modified_environment_is_rejected_before_any_source_change(self):
        stage,_=self.make_environment_plan()
        (stage/"environment/python/pythonw.exe").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"環境檔案已變動"):
            update.apply_update(stage)
        self.assertEqual((self.root/"main.py").read_bytes(),b"print('old')\n")

    def test_environment_failure_relaunches_original_interpreter(self):
        stage,plan=self.make_environment_plan()
        with patch.object(update,"wait_for_exit"),patch.object(update.subprocess,"Popen") as popen:
            popen.return_value.poll.return_value=1
            update.run_worker(stage,"original-pythonw.exe",123)
        self.assertEqual(Path(popen.call_args_list[0].args[0][0]),
            self.root/plan["environment"]["path"]/"python/pythonw.exe")
        self.assertEqual(popen.call_args_list[1].args[0][0],"original-pythonw.exe")
        self.assertIsNone(update.installed_python(self.root))

    def test_source_only_update_keeps_selected_private_environment(self):
        name=".hedge-runtime-"+"d"*32
        python=self.root/name/"python/pythonw.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"existing-env")
        (self.root/update.RECEIPT).write_text(json.dumps({"files":self.before,"environment":name}))
        stage=self.prepare()
        update.apply_update(stage)
        self.assertEqual(update.installed_python(self.root),python)

    def test_environment_path_cannot_retarget_production_or_outside_folder(self):
        for name in ("../trading-workflow-helper", "runtime", "C:/other", ".hedge-runtime-../"):
            with self.subTest(name=name),self.assertRaises(ValueError):
                update.environment_root(self.root,name)

    def test_existing_launcher_redirects_to_private_environment_before_loading_gui(self):
        import main
        stage,_=self.make_environment_plan()
        update.apply_update(stage)
        selected=update.installed_python(self.root)
        with patch.object(main,"APP_BASE",self.root),patch("subprocess.Popen") as launch:
            main.main()
        self.assertEqual(Path(launch.call_args.args[0][0]),selected)
        self.assertEqual(Path(launch.call_args.args[0][1]),self.root/"main.py")
        self.assertEqual(launch.call_count,1)

    def test_production_folder_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "LAB"):
            update.require_lab(self.root.parent / "trading-workflow-helper")

    def test_worker_does_nothing_until_old_process_exits(self):
        stage = self.prepare()
        with patch.object(update, "wait_for_exit", side_effect=TimeoutError), patch.object(update, "apply_update") as apply:
            with self.assertRaises(TimeoutError):
                update.run_worker(stage, "pythonw.exe", 123)
        apply.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows process handles")
    def test_wait_handles_running_and_already_exited_windows_process(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.2)"],
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            update.wait_for_exit(process.pid)
            process.wait(timeout=5)
            update.wait_for_exit(process.pid)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)

    def test_failed_new_start_rolls_back_then_reopens_old_version(self):
        stage = self.prepare()
        with patch.object(update, "wait_for_exit"), patch.object(update.subprocess, "Popen") as popen:
            popen.return_value.poll.return_value = 1
            update.run_worker(stage, "pythonw.exe", 123)
        self.assertEqual((self.root / "main.py").read_bytes(), b"print('old')\n")
        self.assertEqual(popen.call_count, 2)
        self.assertIn("HEDGE_UPDATE_ERROR", popen.call_args.kwargs["env"])

    def test_paths_cannot_escape_install(self):
        for path in ("../main.py", "/main.py", "C:/main.py", "trading_helper/../../secret.py", ""):
            self.assertFalse(update.managed(path))

    def test_new_version_restarts_in_isolated_app_and_signals_ready(self):
        self.files["main.py"] = (
            b"import os, time\nfrom pathlib import Path\n"
            b"Path(os.environ['HEDGE_UPDATE_RECEIPT']).write_text('ready')\ntime.sleep(2)\n")
        stage = self.prepare()
        children = []
        original = update.subprocess.Popen
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            children.append(process)
            return process
        try:
            with patch.object(update, "wait_for_exit"), patch.object(update.subprocess, "Popen", side_effect=launch):
                update.run_worker(stage, sys.executable, 123)
            self.assertTrue((stage / "started").exists())
            self.assertFalse((stage / "error.txt").exists())
            self.assertEqual(len(children), 1)
        finally:
            for process in children:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)

    def test_removed_module_is_backed_up_and_rollback_restores_it(self):
        old = self.root / "trading_helper/obsolete.py"
        old.write_bytes(b"old_module = True\n")
        self.before["trading_helper/obsolete.py"] = update.digest(old.read_bytes())
        (self.root / update.RECEIPT).write_text(json.dumps({"files": self.before}))
        stage = self.prepare()
        plan = update.apply_update(stage)
        self.assertFalse(old.exists())
        update.rollback(stage, plan)
        self.assertEqual(old.read_bytes(), b"old_module = True\n")


class UpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def test_prompt_uses_shared_chrome_and_cannot_close_during_download(self):
        from trading_helper.update_check import UpdateNotice
        from trading_helper.update_ui import UpdateDialog
        dialog = UpdateDialog(UpdateNotice("1.0.0", "1.0.1"), None)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.windowTitle(), "有新版本")
        self.assertTrue(dialog.property("appDialogChrome"))
        self.assertFalse(hasattr(dialog, "chrome_minimize"))
        self.assertFalse(hasattr(dialog, "chrome_maximize"))
        dialog.show()
        dialog.set_busy(True)
        dialog.reject()
        self.assertTrue(dialog.isVisible())
        dialog.set_busy(False)
        dialog.reject()
        self.assertFalse(dialog.isVisible())

    def test_active_or_pending_operations_block_update_and_update_blocks_new_tasks(self):
        from trading_helper.gui import TradingHelperApp
        fake = SimpleNamespace(
            _update_lock=threading.Lock(), _update_in_progress=False,
            _active_tasks=1, _fill_waiting_for_sheet=None,
            _parameter_write_active=False, _parameter_write_pending=False,
            _fill_task_lock=threading.Lock(), log=lambda text: None,
        )
        self.assertFalse(TradingHelperApp.begin_update(fake))
        fake._active_tasks = 0
        fake._parameter_write_pending = True
        self.assertFalse(TradingHelperApp.can_update(fake))
        fake._parameter_write_pending = False
        self.assertTrue(TradingHelperApp.begin_update(fake))
        called = []
        TradingHelperApp._start(fake, "填入兩邊", lambda: called.append(True))
        self.assertFalse(called)
        self.assertFalse(fake._fill_task_lock.locked())
        TradingHelperApp.end_update(fake)
        self.assertTrue(TradingHelperApp.can_update(fake))
