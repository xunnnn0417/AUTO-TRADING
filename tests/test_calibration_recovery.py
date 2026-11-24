"""0.1.79 calibration recovery and role-aware bulk-close page.

Offline only: isolated temporary config, no broker windows, no clicks.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QMainWindow

import test_compact_followup_controls as fixtures
from trading_helper import crash_log
from trading_helper import gui
from trading_helper.bulk_close_calibration import targets
from trading_helper.gui import CalibrationDialog


def roles_parent(internal, external):
    parent = QMainWindow()
    parent.internal_platform = SimpleNamespace(currentText=lambda: internal)
    parent.external_platform = SimpleNamespace(currentText=lambda: external)
    parent.store = SimpleNamespace(data={"ui": {}, "platforms": {
        "MT5": {"points": {}}, "cTrader": {"points": {}}}})
    return parent


class CalibrationRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make_dialog(self, platform="MT5", parent=None):
        parent = parent or QMainWindow()
        dialog = CalibrationDialog(parent, platform)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)
        self.addCleanup(dialog._hover_outline.close)
        return parent, dialog

    def test_dialog_is_restored_even_if_main_window_restore_raises(self):
        for platform in ("cTrader", "MT5"):
            with self.subTest(platform=platform):
                parent, dialog = self.make_dialog(platform)
                parent.operation_hint = gui.QLabel(parent)
                parent._hide_for_operation = Mock()
                parent._restore_after_operation = Mock(side_effect=RuntimeError("dock failed"))
                dialog.show()
                dialog._begin_calibration_operation("離線預覽")
                dialog.setWindowOpacity(0.0)
                dialog._restore_calibration_operation()
                parent._restore_after_operation.assert_called_once_with()
                self.assertIsNone(dialog._calibration_abort)
                self.assertTrue(dialog.isVisible())
                self.assertEqual(dialog.windowOpacity(), 1.0)

    def test_saved_zero_opacity_is_never_restored_as_invisible(self):
        parent, dialog = self.make_dialog()
        parent._hide_for_operation = Mock()
        parent._restore_after_operation = Mock()
        dialog.show()
        dialog.setWindowOpacity(0.0)  # left over from an earlier failure
        dialog._begin_calibration_operation("離線預覽")
        dialog._restore_calibration_operation()
        self.assertEqual(dialog.windowOpacity(), 1.0)

    def test_watchdog_repairs_only_an_idle_transparent_dialog(self):
        parent, dialog = self.make_dialog()
        parent.operation_hint = gui.QLabel(parent)
        parent.operation_hint.show()
        dialog.show()
        dialog.setWindowOpacity(0.0)
        dialog._capture_running = True
        dialog._repair_stranded_transparency()
        self.assertEqual(dialog.windowOpacity(), 0.0, "an active capture stays transparent")
        dialog._capture_running = False
        with patch.object(crash_log, "record") as record:
            dialog._repair_stranded_transparency()
        record.assert_called_once()
        self.assertEqual(dialog.windowOpacity(), 1.0)
        self.assertFalse(parent.operation_hint.isVisible())
        self.assertTrue(dialog._transparency_watchdog.isActive())

    def test_view_position_while_busy_reports_instead_of_silently_skipping(self):
        parent, dialog = self.make_dialog()
        dialog._candidate_preview_running = True
        with patch.object(dialog, "_saved_point_rectangles") as saved, \
             patch.object(dialog, "_preview_saved_calibration") as preview:
            dialog.show_position(show_all=True)
        saved.assert_not_called()
        preview.assert_not_called()
        self.assertIn("還沒結束", dialog.result.text())

    def test_capture_failure_also_pops_a_notification(self):
        parent, dialog = self.make_dialog()
        with patch.object(dialog, "_refresh_stage_progress"), \
             patch.object(gui.QMessageBox, "warning") as warning:
            dialog._finish_capture({"key": "", "error": "游標不在指定場別的平台內，未儲存。"})
        warning.assert_called_once()
        self.assertIn("游標不在", warning.call_args.args[2])
        self.assertIn("擷取失敗", dialog.result.text())

    def test_stage_dot_sits_at_top_right_of_tab_caption(self):
        parent, dialog = self.make_dialog("cTrader")
        bar = dialog._calibration_tabs.tabBar()
        for index, dot in enumerate(dialog._stage_dots):
            host = bar.tabButton(index, gui.QTabBar.RightSide)
            self.assertIs(dot.parent(), host)
            self.assertEqual(dot.pos().y(), 0)
            self.assertGreater(host.height(), dot.height())


class BulkPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_two_shared_fields_are_usable_on_both_platforms(self):
        # One pair per platform, shared by every profile and both sides.
        for platform in ("cTrader", "MT5"):
            with self.subTest(platform=platform):
                parent = roles_parent("cTrader", "MT5")
                dialog = CalibrationDialog(parent, platform)
                for index, (key, _) in enumerate(targets(platform)):
                    self.assertTrue(dialog.radios[key].isEnabled())
                    self.assertNotIn("未使用", dialog.radios[key].text())
                    # The 2nd field waits for the 1st (DemoSafetyAndOrderTests).
                    self.assertEqual(dialog._field_capture_buttons[key].isEnabled(), index == 0)
                last = len(dialog._stage_keys) - 1
                self.assertIn("(0/2)", dialog._calibration_tabs.tabText(last))
                dialog._hover_outline.close()
                dialog.close()
                parent.close()

    def test_mt5_bulk_page_keeps_only_per_field_manual_capture(self):
        page_buttons = {}
        for platform in ("cTrader", "MT5"):
            parent = roles_parent("cTrader", "MT5")
            dialog = CalibrationDialog(parent, platform)
            page = dialog._calibration_tabs.widget(len(dialog._stage_keys) - 1)
            page_buttons[platform] = {b.text() for b in page.findChildren(gui.QPushButton)}
            dialog._hover_outline.close()
            dialog.close()
            parent.close()
        for platform in ("cTrader", "MT5"):
            # One 「自動尋找」 per field; no page-wide search button.
            self.assertIn("自動尋找", page_buttons[platform])
            self.assertNotIn("自動尋找欄位", page_buttons[platform])
            self.assertNotIn("手動擷取", page_buttons[platform])

    def test_bulk_window_lookup_falls_back_to_the_other_bound_side(self):
        app = SimpleNamespace(store=SimpleNamespace(data={"platforms": {"MT5": {
            "window_title": {"internal": "", "external": "Terminal"}}}}))
        self.assertEqual(gui.bulk_binding_role(app, "MT5", "internal"), "external")
        self.assertEqual(gui.bulk_binding_role(app, "MT5", "external"), "external")
        app.store.data["platforms"]["MT5"]["window_title"] = {"internal": "", "external": ""}
        self.assertEqual(gui.bulk_binding_role(app, "MT5", "internal"), "internal")

    def test_capture_on_external_only_mt5_uses_that_window(self):
        parent = roles_parent("cTrader", "MT5")
        parent.store.data["platforms"]["MT5"]["window_title"] = {"internal": "", "external": "Terminal"}
        parent.operation_hint = gui.QLabel(parent)
        parent._hide_for_operation = Mock()
        parent._restore_after_operation = Mock()
        dialog = CalibrationDialog(parent, "MT5")
        dialog.radios["bulk_close_actions"].setChecked(True)
        with patch.object(gui.threading, "Thread") as thread:
            dialog.capture()
        thread.assert_called_once()
        task = thread.call_args.kwargs["target"]
        # Run the worker inline; its deliberate failure reaches the GUI's
        # failure popup, which must be patched or the test would block.
        with patch.object(gui, "_bound_broker_main", side_effect=RuntimeError("stop")) as bound, \
             patch("trading_helper.mouse_guard.PhysicalMouseGuard"), \
             patch.object(gui.QMessageBox, "warning") as warning:
            task()
        warning.assert_called_once()
        self.assertEqual(bound.call_args.args[2], "external")
        self.assertFalse(dialog._capture_running)
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_bulk_capture_uses_five_second_countdown_and_menu_instructions(self):
        parent = roles_parent("cTrader", "MT5")
        parent.operation_hint = gui.QLabel(parent)
        parent._hide_for_operation = Mock()
        parent._restore_after_operation = Mock()
        parent.set_operation_hint_text = Mock()
        dialog = CalibrationDialog(parent, "MT5")
        dialog.radios["bulk_close_all"].setChecked(True)
        with patch.object(gui.threading, "Thread") as thread:
            dialog.capture()
        thread.assert_called_once()
        hint = parent.set_operation_hint_text.call_args.args[0]
        self.assertIn("往右", hint)
        self.assertIn("所有持倉平倉", hint)
        self.assertIn("不會點擊", hint)
        dialog._finish_capture({"cancelled": True})
        dialog._hover_outline.close()
        dialog.close()
        parent.close()


class MainScreenTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def test_missing_bulk_fields_remind_on_the_main_button(self):
        w = self.w
        all_keys = [key for key, _ in gui.CALIBRATION_TARGETS["MT5"]]
        points = w.store.data["platforms"]["MT5"]["points"]
        for key in all_keys:
            if "bulk_close" not in key:
                points[key] = {"x": 0.5, "y": 0.5}
        w._refresh_calibration_badges()
        button = w.action_buttons["校準 MT5"]
        dot = w._calibration_badge_labels[button]
        self.assertIn(f"/{len(all_keys)}", button.toolTip())
        if w.show_calibration_badges.isChecked():
            self.assertTrue(dot.isVisibleTo(button))
        for key in all_keys:
            points[key] = {"x": 0.5, "y": 0.5}
        w._refresh_calibration_badges()
        self.assertFalse(dot.isVisibleTo(button))

    def test_rest_close_checkbox_then_gear_after_a_divider(self):
        w = self.w
        checkbox = w.rest_close_checkbox
        button = w.rest_close_settings_button
        row = button.parentWidget()
        layout = row.layout()
        separator = row.findChild(gui.QFrame, "restCloseSeparator")
        self.assertIsInstance(checkbox, gui.QCheckBox)
        self.assertEqual(checkbox.text(), "休市平倉")
        self.assertEqual(
            [layout.indexOf(separator), layout.indexOf(checkbox), layout.indexOf(button)],
            sorted([layout.indexOf(separator), layout.indexOf(checkbox), layout.indexOf(button)]))
        self.assertEqual(layout.indexOf(checkbox) + 1, layout.indexOf(button))
        self.assertEqual(button.text(), "")
        self.assertTrue(button.autoRaise())
        self.assertFalse(checkbox.isChecked())
        with patch.object(gui.RestCloseSettingsDialog, "exec", return_value=0) as shown:
            button.click()
        shown.assert_called_once()

    def test_enabling_rest_close_asks_first_and_only_saves_a_setting(self):
        w = self.w
        with patch.object(w, "_confirm_rest_close_enable", return_value=False),              patch.object(w, "save_config") as save:
            w.rest_close_checkbox.setChecked(True)
        self.assertFalse(w.rest_close_checkbox.isChecked())
        save.assert_not_called()
        with patch.object(w, "_confirm_rest_close_enable", return_value=True),              patch.object(w, "save_config") as save:
            w.rest_close_checkbox.setChecked(True)
        self.assertTrue(w.store.data["ui"]["rest_close_enabled"])
        save.assert_called_once()
        with patch.object(w, "save_config"):
            w.rest_close_checkbox.setChecked(False)
        self.assertFalse(w.store.data["ui"]["rest_close_enabled"])


class MobileIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_phone_icons_use_the_desktop_logo(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        from trading_helper import remote_mobile
        desktop = remote_mobile._desktop_icon()
        self.assertIsNotNone(desktop, "assets/app.ico must be readable")
        for path, size in (("/icon-180.png", 180), ("/icon-192.png", 192), ("/icon-512.png", 512)):
            image = QImage.fromData(remote_mobile.ASSETS[path][1], "PNG")
            self.assertEqual((image.width(), image.height()), (size, size))
            expected = desktop.convertToFormat(QImage.Format_ARGB32).scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            for x, y in ((size // 2, size // 2), (2, 2), (size // 4, size // 2)):
                self.assertEqual(image.pixelColor(x, y).name(), expected.pixelColor(x, y).name())
            # The old drawn icon was a solid purple (#7150dc) square.
            self.assertNotEqual(image.pixelColor(size // 2, size // 2).name(), "#7150dc")
        self.assertNotIn("/icon.svg", remote_mobile.ASSETS)
        self.assertIn('href="/icon-192.png"', remote_mobile.HTML)


class CalibrationAbortGuardTests(unittest.TestCase):
    def test_abort_works_as_window_controller_emergency(self):
        # MT5 bulk capture right-clicks via WindowController(abort); 0.1.78
        # crashed with "'_CalibrationAbort' object has no attribute 'guard'".
        abort = gui._CalibrationAbort()
        abort.guard()
        abort.stop()
        with self.assertRaises(gui.EmergencyStopped):
            abort.guard()

    def test_right_click_path_reaches_the_platform_without_attribute_error(self):
        abort = gui._CalibrationAbort()
        controller = gui.WindowController(abort)
        window = gui.WindowInfo(5, "Terminal", 0, 0, 800, 600)
        with patch.object(controller, "focus", return_value=window) as focus,              patch.object(controller, "_validate_calibrated_window"),              patch.object(controller, "screen_point", return_value=(100, 200)),              patch("pyautogui.click") as click:
            controller.right_click(window, {"x": 0.5, "y": 0.5})
        focus.assert_called_once_with(window)
        click.assert_called_once_with(100, 200, button="right")


class CrashLogTests(unittest.TestCase):
    def test_record_writes_only_when_enabled_or_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "errors.log"
            with patch.object(crash_log, "log_path", return_value=target), \
                 patch.object(crash_log, "_enabled", False):
                try:
                    raise ValueError("offline")
                except ValueError:
                    crash_log.record("test")
            self.assertFalse(target.exists())
            try:
                raise ValueError("offline explicit")
            except ValueError:
                crash_log.record("test", path=target)
            self.assertIn("ValueError: offline explicit", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class AppLifetimeAndProfileNameTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def test_main_window_close_signals_app_exit_but_popups_do_not(self):
        # main.py quits only on this signal (setQuitOnLastWindowClosed(False)),
        # so a parentless popup closed while the main window is hidden for a
        # sidebar fill no longer ends the whole helper.
        closed = []
        self.w.main_window_closed.connect(lambda: closed.append(True))
        self.w.hide()
        box = gui.ThemedMessageBox(None)
        box.show()
        box.close()
        self.assertEqual(closed, [])
        self.w.close()
        self.assertEqual(closed, [True])

    def test_main_py_quits_on_main_window_close_only(self):
        source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertIn("setQuitOnLastWindowClosed(False)", source)
        self.assertIn("main_window_closed.connect(qt.quit)", source)

    def test_new_profile_name_is_prefilled_with_next_free_number(self):
        self.assertEqual(gui.next_profile_name([]), "方案1")
        self.assertEqual(gui.next_profile_name(["測試", "方案1"]), "方案2")
        self.assertEqual(gui.next_profile_name(["方案1", "方案3"]), "方案2")
        with patch("trading_helper.gui.themed_input_text", return_value=("", False)) as prompt:
            self.w.create_profile()
        expected = gui.next_profile_name(self.w.profiles.names())
        self.assertEqual(prompt.call_args.args[3], expected)


class SharedUser32Tests(unittest.TestCase):
    def test_preview_monitor_lookup_does_not_retype_shared_user32(self):
        # 0.1.78: a calibration preview set GetMonitorInfoW.argtypes on the
        # shared ctypes.windll.user32; sidebar docking then raised
        # "expected LP__MonitorInfo instance", breaking profile switching.
        import ctypes
        from trading_helper import ui_inspector
        shared = ctypes.windll.user32.GetMonitorInfoW
        before = shared.argtypes
        ui_inspector._native_monitor_at(0, 0)
        self.assertEqual(shared.argtypes, before)

    def test_sidebar_monitor_lookup_survives_a_foreign_argtype(self):
        import ctypes
        from ctypes import wintypes
        from trading_helper import sidebar_geometry

        class Foreign(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD)]

        shared = ctypes.windll.user32.GetMonitorInfoW
        before = shared.argtypes
        shared.argtypes = [wintypes.HANDLE, ctypes.POINTER(Foreign)]
        try:
            widget = SimpleNamespace(winId=lambda: 0, x=lambda: 0, y=lambda: 0,
                                     width=lambda: 1, height=lambda: 1, collapsed=False)
            screen = QApplication.instance().primaryScreen() if QApplication.instance() else None
            with patch.object(sidebar_geometry.QGuiApplication, "platformName", return_value="windows"):
                # Must not raise ctypes.ArgumentError out of the docking code.
                sidebar_geometry.ensure_native_sidebar(widget, screen, 0)
        finally:
            shared.argtypes = before


class Mt5MenuHoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_hover_moves_to_bulk_actions_centre_and_never_clicks(self):
        from trading_helper import bulk_close_calibration as bulk
        moved = []
        with patch.object(bulk, "find_mt5_menu_item", return_value=(100, 200, 300, 220)) as find,              patch.object(bulk, "_expand_mt5_item", return_value=True) as expand:
            bulk.hover_mt5_bulk_actions("main", lambda _h: 7, lambda x, y: moved.append((x, y)))
        self.assertEqual(find.call_args_list[0].args[1], "bulk_close_actions")
        self.assertEqual(find.call_args_list[-1].args[1], "bulk_close_all")  # submenu verified
        self.assertEqual(expand.call_args.args[1], (100, 200, 300, 220))
        self.assertEqual(moved, [])  # UIA expand opened it: no click at all
        with patch.object(bulk, "find_mt5_menu_item", return_value=(100, 200, 300, 220)),              patch.object(bulk, "_expand_mt5_item", return_value=False):
            bulk.hover_mt5_bulk_actions("main", lambda _h: 7, lambda x, y: moved.append((x, y)))
        self.assertEqual(moved, [(200, 210)])  # fallback: header click only
        moved.clear()
        # Expand ignored the first time: retry, and the submenu shows.
        found = iter([(100, 200, 300, 220), None, (1, 1, 2, 2)])
        with patch.object(bulk, "find_mt5_menu_item", side_effect=lambda *a, **k: next(found)),              patch.object(bulk, "_expand_mt5_item", return_value=True) as expand:
            bulk.hover_mt5_bulk_actions("main", lambda _h: 7, lambda x, y: moved.append((x, y)))
        self.assertEqual(expand.call_count, 2)
        self.assertEqual(moved, [])
        with patch.object(bulk, "find_mt5_menu_item", return_value=None):
            with self.assertRaises(bulk.AutomationError):
                bulk.hover_mt5_bulk_actions("main", lambda _h: 7, lambda x, y: moved.append((x, y)))
        self.assertEqual(moved, [])

    def test_submenu_capture_rests_on_bulk_actions_after_the_right_click(self):
        parent = roles_parent("cTrader", "MT5")
        parent.store.data["platforms"]["MT5"]["points"]["position_order_row"] = {"x": 0.5, "y": 0.5}
        parent.operation_hint = gui.QLabel(parent)
        parent._hide_for_operation = Mock()
        parent._restore_after_operation = Mock()
        dialog = CalibrationDialog(parent, "MT5")
        dialog.radios["bulk_close_all"].setChecked(True)
        with patch.object(gui.threading, "Thread") as thread:
            dialog.capture()
        task = thread.call_args.kwargs["target"]
        order = []
        window = gui.WindowInfo(5, "Terminal", 0, 0, 800, 600)
        with patch.object(gui, "_bound_broker_main", return_value=window), \
             patch.object(gui.WindowController, "focus",
                          side_effect=lambda win: (order.append("focus"), win)[1]), \
             patch("trading_helper.mouse_guard.PhysicalMouseGuard"), \
             patch.object(gui, "open_mt5_context", side_effect=lambda *a: order.append("right-click")), \
             patch.object(gui, "hover_mt5_bulk_actions", side_effect=lambda *a: order.append("hover")), \
             patch.object(gui.QMessageBox, "warning"):
            abort = dialog._calibration_abort
            original_wait = abort.event.wait
            abort.event.wait = lambda _t=None: (abort.event.set(), True)[1]  # cancel at first tick
            task()
            abort.event.wait = original_wait
        self.assertEqual(order, ["focus", "right-click", "hover"])
        dialog._hover_outline.close()
        dialog.close()
        parent.close()

    def test_preview_opens_menu_once_and_hovers_only_for_submenu_item(self):
        parent = roles_parent("cTrader", "MT5")
        parent.windows = Mock(spec=gui.WindowController)
        dialog = CalibrationDialog(parent, "MT5")
        calls = []
        with patch.object(gui, "open_mt5_context", side_effect=lambda *a: calls.append("right-click")),              patch.object(gui, "hover_mt5_bulk_actions", side_effect=lambda *a: calls.append("hover")),              patch.object(gui, "find_mt5_menu_item", side_effect=[(1, 2, 3, 4), (5, 6, 7, 8)]):
            dialog._preview_menu_open = False
            first = dialog._open_mt5_bulk_menu_for_preview("main", "bulk_close_actions", {})
            second = dialog._open_mt5_bulk_menu_for_preview("main", "bulk_close_all", {})
        self.assertEqual((first, second), ((1, 2, 3, 4), (5, 6, 7, 8)))
        self.assertEqual(calls, ["right-click", "hover"])
        dialog._hover_outline.close()
        dialog.close()
        parent.close()


class ProfileSwitchSyncTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def _second_profile(self):
        original = self.w.profiles.active_name
        self.w.profiles.create("手機方案", self.w.store.data)
        self.w.profiles.set_active(original)
        self.w._refresh_profile_combo(original)
        return original, "手機方案"

    def test_phone_switch_updates_the_desktop_selector(self):
        original, other = self._second_profile()
        with patch.object(self.w, "read_sheet"):
            self.w.switch_profile(other)  # what the phone's "profile" action calls
        self.assertEqual(self.w.profiles.active_name, other)
        self.assertEqual(self.w.profile_combo.currentText(), other)

    def test_failed_switch_rolls_data_back_so_screen_and_data_agree(self):
        original, other = self._second_profile()
        real_apply = self.w._apply_profile_ui
        calls = []

        def apply_once_failing():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("Internal C++ object (PySide6.QtGui.QScreen) already deleted.")
            real_apply()

        with patch.object(self.w, "_apply_profile_ui", side_effect=apply_once_failing), \
             patch.object(self.w, "read_sheet"), \
             patch.object(gui.QMessageBox, "critical") as critical:
            self.w.switch_profile(other)
        critical.assert_called_once()
        self.assertEqual(self.w.profiles.active_name, original)
        self.assertEqual(self.w.profile_combo.currentText(), original)
        self.assertEqual(self.w.automation.profile_name, original)


class UnboundWindowMessageTests(unittest.TestCase):
    def test_unbound_side_names_the_profile_and_what_to_do(self):
        app = SimpleNamespace(
            store=SimpleNamespace(data={"platforms": {"MT5": {"window_title": {"internal": "", "external": ""}}}}),
            profiles=SimpleNamespace(active_name="實戰"),
            windows=Mock(),
        )
        with self.assertRaises(gui.AutomationError) as caught:
            gui._bound_broker_main(app, "MT5", "external", display_only=True)
        message = str(caught.exception)
        self.assertIn("實戰", message)
        self.assertIn("場外", message)
        self.assertIn("綁定場外視窗", message)
        app.windows.find.assert_not_called()


class Mt5BulkAutoFindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make(self, row=True):
        parent = roles_parent("cTrader", "MT5")
        if row:
            parent.store.data["platforms"]["MT5"]["points"]["position_order_row"] = {"x": 0.5, "y": 0.5}
        parent.operation_hint = gui.QLabel(parent)
        parent._hide_for_operation = Mock()
        parent._restore_after_operation = Mock()
        parent.windows = Mock(spec=gui.WindowController)
        parent.windows.list_windows.return_value = []
        dialog = CalibrationDialog(parent, "MT5")
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)
        self.addCleanup(dialog._hover_outline.close)
        return parent, dialog

    def test_requires_the_sl_cell_first_and_starts_nothing(self):
        parent, dialog = self.make(row=False)
        with patch.object(gui.threading, "Thread") as thread,              patch.object(gui.QMessageBox, "warning") as warning:
            dialog.auto_find_mt5_bulk()
        thread.assert_not_called()
        self.assertIn("SL 欄", warning.call_args.args[2])

    def test_reads_both_items_while_menu_open_then_saves_only_after_confirm(self):
        parent, dialog = self.make()
        window = gui.WindowInfo(5, "Terminal", 0, 0, 800, 600)
        calls = []
        with patch.object(gui, "_bound_broker_main", return_value=window),              patch.object(gui.threading, "Thread") as thread:
            dialog.auto_find_mt5_bulk()
        task = thread.call_args.kwargs["target"]
        found = {}
        dialog.mt5_bulk_found.disconnect()
        dialog.mt5_bulk_found.connect(lambda result: found.update(result))
        with patch("trading_helper.mouse_guard.PhysicalMouseGuard"), \
             patch.object(gui.WindowController, "focus",
                          side_effect=lambda win: (calls.append("focus"), win)[1]), \
             patch.object(gui, "open_mt5_context", side_effect=lambda *a: calls.append("right-click")), \
             patch.object(gui, "hover_mt5_bulk_actions", side_effect=lambda *a: calls.append("open-submenu")), \
             patch.object(gui, "find_mt5_menu_item", side_effect=[(10, 10, 90, 30), (100, 40, 200, 60)]), \
             patch.object(gui, "process_id_for_window", return_value=7), \
             patch.object(gui, "candidate_calibration_points",
                          side_effect=lambda report, keys, *a: {k: {"x": 0.1, "y": 0.2} for k in keys}):
            task()
        self.assertEqual(calls, ["focus", "right-click", "open-submenu"])
        self.assertEqual(set(found["points"]), {"bulk_close_actions", "bulk_close_all"})
        dialog._inventory_running = True
        dialog._calibration_abort = gui._CalibrationAbort()
        with patch.object(gui, "save_confirmed_points") as save, \
             patch.object(gui.ThemedMessageBox, "exec"), \
             patch.object(gui.ThemedMessageBox, "clickedButton",
                          lambda box: next(b for b in box._buttons if b.text() == "儲存這些位置")):
            dialog._finish_mt5_bulk_find(found)
        save.assert_called_once()
        self.assertFalse(dialog._inventory_running)

    def test_title_bar_close_never_saves(self):
        parent, dialog = self.make()
        dialog._calibration_abort = gui._CalibrationAbort()
        with patch.object(gui, "save_confirmed_points") as save, \
             patch.object(gui.ThemedMessageBox, "exec"), \
             patch.object(gui.ThemedMessageBox, "clickedButton", return_value=None):  # ✕
            dialog._finish_mt5_bulk_find({"points": {"bulk_close_actions": {"x": 0.1, "y": 0.1}}})
        save.assert_not_called()

    def test_declining_saves_nothing(self):
        parent, dialog = self.make()
        dialog._calibration_abort = gui._CalibrationAbort()
        captured = {}
        real_add = gui.ThemedMessageBox.addButton
        def add_button(box, text, role):
            button = real_add(box, text, role)
            captured.setdefault("first", button)
            return button
        with patch.object(gui, "save_confirmed_points") as save,              patch.object(gui.ThemedMessageBox, "addButton", add_button),              patch.object(gui.ThemedMessageBox, "exec"),              patch.object(gui.ThemedMessageBox, "clickedButton", lambda box: captured["first"]):
            dialog._finish_mt5_bulk_find({"points": {"bulk_close_actions": {"x": 0.1, "y": 0.1}}})
        save.assert_not_called()


class PerFieldButtonsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make(self, platform):
        parent = roles_parent("cTrader", "MT5")
        dialog = CalibrationDialog(parent, platform)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)
        self.addCleanup(dialog._hover_outline.close)
        return parent, dialog

    def test_saved_field_hides_its_button_until_cleared_for_every_capture_field(self):
        for platform in ("cTrader", "MT5", "TradingView"):
            with self.subTest(platform=platform):
                parent, dialog = self.make(platform)
                parent.store.data["platforms"].setdefault(platform, {"points": {}})
                points = parent.store.data["platforms"][platform].setdefault("points", {})
                buttons = dict(dialog._field_capture_buttons)
                close_button = getattr(dialog, "position_close_capture_button", None)
                if close_button is not None:
                    buttons["position_close_button"] = close_button
                self.assertTrue(buttons)
                for key in buttons:
                    points[key] = {"x": 0.5, "y": 0.5}
                dialog._refresh_stage_progress()
                self.assertTrue(all(b.isHidden() for b in buttons.values()))
                points.clear()
                dialog._refresh_stage_progress()
                self.assertFalse(any(b.isHidden() for b in buttons.values()))

    def test_per_field_auto_find_routes_by_platform(self):
        parent, dialog = self.make("MT5")
        parent.store.data["platforms"]["MT5"]["points"]["bulk_close_actions"] = {"x": 0.5, "y": 0.5}
        dialog._refresh_stage_progress()  # 1st saved -> 2nd unlocked
        with patch.object(dialog, "auto_find_mt5_bulk") as mt5:
            dialog._field_capture_buttons["bulk_close_all"].click()
        mt5.assert_called_once_with(("bulk_close_all",))
        self.assertTrue(dialog.radios["bulk_close_all"].isChecked())
        parent, dialog = self.make("cTrader")
        with patch.object(dialog, "auto_find_ctrader_bulk") as ctrader:
            dialog._field_capture_buttons["bulk_close_button"].click()
        ctrader.assert_called_once_with("bulk_close_button")

    def test_failed_search_offers_manual_capture_only_on_that_button(self):
        failed = {"points": {}, "missing": ["子選單：所有持倉平倉"],
                  "seen": ["所有持倉平倉", "盈利持倉平倉"]}
        parent, dialog = self.make("MT5")
        dialog._calibration_abort = gui._CalibrationAbort()
        with patch.object(dialog, "capture") as capture, \
             patch.object(gui.ThemedMessageBox, "exec"), \
             patch.object(gui.ThemedMessageBox, "clickedButton",
                          lambda box: next(b for b in box._buttons if b.text() == "改用手動擷取")):
            dialog._finish_mt5_bulk_find(failed)
        capture.assert_called_once_with()
        dialog._calibration_abort = gui._CalibrationAbort()
        with patch.object(dialog, "capture") as capture, \
             patch.object(gui.ThemedMessageBox, "exec"), \
             patch.object(gui.ThemedMessageBox, "clickedButton", return_value=None):  # ✕
            dialog._finish_mt5_bulk_find(failed)
        capture.assert_not_called()

    def test_ctrader_search_focuses_then_reads_without_clicking(self):
        parent, dialog = self.make("cTrader")
        parent.windows = Mock()
        parent.windows.list_windows.return_value = []
        window = gui.WindowInfo(9, "cTrader 5.10.22", 0, 0, 1920, 1020)
        order = []
        with patch.object(gui, "_bound_broker_main", return_value=window), \
             patch.object(gui.threading, "Thread") as thread:
            dialog.auto_find_ctrader_bulk("bulk_close_button")
        task = thread.call_args.kwargs["target"]
        found = {}
        dialog.mt5_bulk_found.disconnect()
        dialog.mt5_bulk_found.connect(lambda result: found.update(result))
        report = gui.ScanReport("cTrader", (("bulk_close_button", "全部平倉按鈕"),))
        report.candidates["bulk_close_button"] = gui.ScanCandidate("bulk_close_button", (1, 2, 3, 4), "")
        with patch("trading_helper.mouse_guard.PhysicalMouseGuard"), \
             patch.object(gui.WindowController, "focus",
                          side_effect=lambda win: (order.append("focus"), win)[1]), \
             patch.object(gui, "inspect_bulk_targets",
                          side_effect=lambda *a: (order.append("read"), report)[1]), \
             patch.object(gui, "process_id_for_window", return_value=3), \
             patch.object(gui, "candidate_calibration_points",
                          return_value={"bulk_close_button": {"x": 0.7, "y": 0.5}}), \
             patch("pyautogui.click") as click:
            task()
        self.assertEqual(order, ["focus", "read"])
        click.assert_not_called()
        self.assertEqual(set(found["points"]), {"bulk_close_button"})


class DemoSafetyAndOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make(self, platform, saved=()):
        parent = roles_parent("cTrader", "MT5")
        parent.store.data["platforms"].setdefault(platform, {"points": {}})
        points = parent.store.data["platforms"][platform].setdefault("points", {})
        for key in saved:
            points[key] = {"x": 0.5, "y": 0.5}
        dialog = CalibrationDialog(parent, platform)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)
        self.addCleanup(dialog._hover_outline.close)
        return parent, dialog

    def test_demo_account_reminder_on_broker_calibration_only(self):
        for platform, expected in (("cTrader", True), ("MT5", True), ("TradingView", False)):
            with self.subTest(platform=platform):
                _, dialog = self.make(platform)
                note = dialog.findChild(gui.QLabel, "calibrationDemoAccountNote")
                self.assertEqual(note is not None, expected)
                if note is not None:
                    self.assertIn("模擬帳戶", note.text())

    def test_second_bulk_field_locked_until_first_is_saved(self):
        for platform, (first, second) in (("MT5", ("bulk_close_actions", "bulk_close_all")),
                                          ("cTrader", ("bulk_close_button", "bulk_close_confirm"))):
            with self.subTest(platform=platform):
                parent, dialog = self.make(platform)
                self.assertTrue(dialog._field_capture_buttons[first].isEnabled())
                self.assertFalse(dialog._field_capture_buttons[second].isEnabled())
                parent.store.data["platforms"][platform]["points"][first] = {"x": 0.5, "y": 0.5}
                dialog._refresh_stage_progress()
                self.assertTrue(dialog._field_capture_buttons[second].isEnabled())

    def test_ctrader_yes_needs_explicit_demo_confirmation_before_anything(self):
        parent, dialog = self.make("cTrader", saved=("bulk_close_button",))
        window = gui.WindowInfo(9, "cTrader 5.10.22", 0, 0, 1920, 1020)
        with patch.object(gui, "_bound_broker_main", return_value=window), \
             patch.object(gui.ThemedMessageBox, "exec"), \
             patch.object(gui.ThemedMessageBox, "clickedButton", return_value=None), \
             patch.object(gui.threading, "Thread") as thread:
            dialog.auto_find_ctrader_bulk("bulk_close_confirm")  # ✕ on the reminder
        thread.assert_not_called()

    def test_ctrader_yes_stops_unless_the_account_reads_demo(self):
        parent, dialog = self.make("cTrader")
        parent.windows = Mock()
        controller = Mock()
        window = gui.WindowInfo(9, "cTrader", 0, 0, 1920, 1020)
        with patch.object(gui, "ctrader_account_type", return_value="Live"), \
             patch.object(gui, "process_id_for_window", return_value=3):
            with self.assertRaises(gui.AutomationError):
                dialog._find_ctrader_yes(controller, window, {"x": 0.5, "y": 0.5}, gui._CalibrationAbort())
        controller.click.assert_not_called()

    def test_ctrader_yes_opens_confirmation_reads_yes_then_cancels_never_yes(self):
        parent, dialog = self.make("cTrader")
        parent.windows = Mock()
        parent.windows.list_windows.return_value = []
        controller = Mock()
        window = gui.WindowInfo(9, "cTrader", 0, 0, 1920, 1020)
        confirmation = {"yes": (800, 500, 860, 530), "cancel": (880, 500, 940, 530)}
        states = iter([None, confirmation])
        clicked = []
        with patch.object(gui, "ctrader_account_type", return_value="Demo"), \
             patch.object(gui, "process_id_for_window", return_value=3), \
             patch.object(gui, "find_ctrader_confirmation", side_effect=lambda *a: next(states)), \
             patch.object(gui, "candidate_calibration_points",
                          return_value={"bulk_close_confirm": {"x": 0.4, "y": 0.5}}), \
             patch("pyautogui.click", side_effect=lambda x, y: clicked.append((x, y))), \
             patch("pyautogui.press") as press, \
             patch.object(gui.time, "sleep"):
            points, reason, yes_rect, dismiss = dialog._find_ctrader_yes(
                controller, window, {"x": 0.5, "y": 0.5}, gui._CalibrationAbort())
            controller.click.assert_called_once()  # close-all, to open the confirmation
            self.assertEqual(clicked, [])           # the search itself clicks nothing else
            self.assertEqual(yes_rect, (800, 500, 860, 530))
            # The decision step shows the box, then cancels — ✕ here = don't save.
            dialog._calibration_abort = gui._CalibrationAbort()
            hidden_while_asking = []
            order = []
            real_dismiss = dialog._dismiss_preview_confirmation
            real_restore = dialog._restore_calibration_operation
            with patch.object(gui.ThemedMessageBox, "exec",
                              side_effect=lambda: hidden_while_asking.append(dialog._calibration_abort is not None)), \
                 patch.object(gui.ThemedMessageBox, "clickedButton", return_value=None), \
                 patch.object(dialog, "_dismiss_preview_confirmation",
                              side_effect=lambda: (order.append("dismiss"), real_dismiss())), \
                 patch.object(dialog, "_restore_calibration_operation",
                              side_effect=lambda: (order.append("restore"), real_restore())), \
                 patch.object(gui.QEventLoop, "exec"), \
                 patch.object(gui.CandidateOutline, "display") as shown:
                dialog._finish_mt5_bulk_find({"points": points, "rects": {"bulk_close_confirm": yes_rect},
                                              "dismiss": dismiss})
            shown.assert_called_once()
            self.assertEqual(hidden_while_asking, [True])  # dialog not restored until decided
            self.assertEqual(order[:2], ["dismiss", "restore"])  # cancel before dialog returns
        self.assertEqual(clicked, [(910, 515)])  # centre of No/Cancel
        self.assertNotIn((830, 515), clicked)   # centre of Yes - never clicked
        press.assert_not_called()
        self.assertEqual(set(points), {"bulk_close_confirm"})
        self.assertEqual(reason, "")
