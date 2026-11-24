"""兩邊平倉 / 休市平倉: exact clicks, two confirmations, countdown window."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import itertools
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from trading_helper import close_both


class Abort:
    def guard(self):
        pass


class CloseCTraderTests(unittest.TestCase):
    def test_nothing_to_close_clicks_nothing(self):
        clicks = []
        with patch.object(close_both, "ctrader_close_all_state", return_value=((0, 0, 10, 10), "Nothing to close")):
            text = close_both.close_ctrader(Mock(), "main", {}, list, lambda h: 1, Abort(),
                                            lambda x, y: clicks.append((x, y)))
        self.assertEqual(clicks, [])
        self.assertIn("沒有持倉", text)

    def test_clicks_close_all_then_yes_and_verifies(self):
        clicks = []
        states = iter([((100, 100, 200, 120), "Close 2"), (None, "Nothing to close")])
        with patch.object(close_both, "ctrader_close_all_state", side_effect=lambda w: next(states)), \
             patch.object(close_both, "find_ctrader_confirmation",
                          return_value={"yes": (300, 300, 340, 320), "cancel": None}), \
             patch.object(close_both.time, "sleep"):
            text = close_both.close_ctrader(Mock(), "main", {}, list, lambda h: 1, Abort(),
                                            lambda x, y: clicks.append((x, y)))
        self.assertEqual(clicks, [(150, 110), (320, 310)])
        self.assertIn("已平倉", text)


class CloseMt5Tests(unittest.TestCase):
    def test_greyed_item_means_no_positions_and_is_not_clicked(self):
        clicks, keys = [], []
        with patch.object(close_both, "open_mt5_context"), \
             patch.object(close_both, "hover_mt5_bulk_actions"), \
             patch.object(close_both, "find_mt5_menu_item", return_value=(10, 10, 50, 30)), \
             patch.object(close_both, "last_mt5_match_enabled", return_value=False):
            text = close_both.close_mt5(Mock(), "main", {"position_order_row": {"x": 1}}, lambda h: 1,
                                        Abort(), lambda x, y: clicks.append((x, y)), keys.append)
        self.assertEqual(clicks, [])
        self.assertEqual(keys, ["esc"] * 3)
        self.assertIn("沒有持倉", text)

    def test_clicks_close_all_item(self):
        clicks = []
        with patch.object(close_both, "open_mt5_context"), \
             patch.object(close_both, "hover_mt5_bulk_actions"), \
             patch.object(close_both, "find_mt5_menu_item", return_value=(10, 10, 50, 30)), \
             patch.object(close_both, "last_mt5_match_enabled", return_value=True):
            close_both.close_mt5(Mock(), "main", {"position_order_row": {"x": 1}}, lambda h: 1,
                                 Abort(), lambda x, y: clicks.append((x, y)), lambda k: None)
        self.assertEqual(clicks, [(30, 20)])

    def test_missing_calibration_is_reported(self):
        self.assertIn("全部平倉按鈕", close_both.missing_calibration("cTrader", {}))
        self.assertIn("持倉列表", close_both.missing_calibration("MT5", {}))
        self.assertEqual(close_both.missing_calibration("MT5", {"position_order_row": {"x": 1}}), "")


class RestCloseTimeTests(unittest.TestCase):
    def test_next_time_is_rest_start_minus_chosen_minutes(self):
        from trading_helper.gui import next_rest_close_time, rest_close_minutes
        data = {"ui": {"rest_close_minutes": 15}}
        self.assertEqual(rest_close_minutes(data), 15)
        self.assertEqual(rest_close_minutes({"ui": {"rest_close_minutes": 7}}), 7)      # custom
        self.assertEqual(rest_close_minutes({"ui": {"rest_close_minutes": 999}}), 15)   # out of range
        self.assertEqual(rest_close_minutes({}), 15)
        now = datetime(2026, 11, 24, 0, 0, tzinfo=timezone(timedelta(hours=8)))  # Tue 00:00 Taipei (winter)
        when = next_rest_close_time(data, now)
        self.assertEqual(when.astimezone(timezone(timedelta(hours=8))).strftime("%H:%M"), "05:45")



import test_compact_followup_controls as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from trading_helper import gui  # noqa: E402


class CloseBothConfirmationTests(unittest.TestCase):
    setUp = fixtures.CompactFollowUpControlsTests.setUp
    tearDown = fixtures.CompactFollowUpControlsTests.tearDown

    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def ready_plan(self):
        return patch.object(self.w, "_close_both_sides_plan",
                            return_value=([("internal", "場內", "cTrader", {}), ("external", "場外", "MT5", {})], []))

    def answer(self, *labels):
        """Each confirmation clicks the button with the given text (None = ✕)."""
        answers = iter(labels)

        def exec_(box):
            label = next(answers)
            box._clicked_button = next((b for b in box._buttons if b.text() == label), None)
            return 0
        return patch.object(gui.ThemedMessageBox, "exec", exec_)

    def test_main_button_exists_and_needs_two_confirmations(self):
        self.assertEqual(self.w.close_both_button.text(), "兩邊平倉")
        for labels in (("取消",), (None,), ("下一步", "取消"), ("下一步", None)):
            with self.ready_plan(), self.answer(*labels), patch.object(self.w, "_start") as start:
                self.w.close_both_sides()
            start.assert_not_called()
        with self.ready_plan(), self.answer("下一步", "立即兩邊平倉"), patch.object(self.w, "_start") as start:
            self.w.close_both_sides()
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0], "兩邊平倉")

    def test_missing_calibration_stops_before_any_question(self):
        with patch.object(self.w, "_close_both_sides_plan", return_value=([], ["場內：cTrader 還沒校準"])), \
             patch.object(gui.ThemedMessageBox, "warning") as warning, \
             patch.object(self.w, "_start") as start:
            self.w.close_both_sides()
        warning.assert_called_once()
        start.assert_not_called()

    def test_rest_close_countdown_cancel_and_timeout(self):
        with self.answer("取消這次（30）"), patch.object(self.w, "close_both_sides") as close:
            self.w._start_rest_close_countdown()
        close.assert_not_called()

        def run_out(box):
            box._clicked_button = None
            return 1
        with patch.object(gui.ThemedMessageBox, "exec", run_out), \
             patch.object(self.w, "close_both_sides") as close:
            self.w._start_rest_close_countdown(seconds=0)
        close.assert_called_once_with(confirmed=True)

    def test_settings_offer_15_30_45_60_and_custom(self):
        self.w.store.data["ui"]["rest_close_minutes"] = 20
        with patch.object(self.w, "save_config"):
            dialog = gui.RestCloseSettingsDialog(self.w)
            self.addCleanup(dialog.close)
            labels = [dialog.minutes_combo.itemText(i) for i in range(dialog.minutes_combo.count())]
            self.assertEqual(labels, ["15 分鐘", "30 分鐘", "45 分鐘", "1 小時", "自訂"])
            self.assertEqual(dialog.minutes_combo.currentText(), "自訂")
            self.assertEqual(dialog.custom_minutes.value(), 20)
            dialog.minutes_combo.setCurrentIndex(2)
        self.assertEqual(self.w.store.data["ui"]["rest_close_minutes"], 45)

    def test_rest_close_runs_once_and_only_in_its_window(self):
        self.w.store.data["ui"]["rest_close_enabled"] = True
        self.w.store.data["ui"]["rest_close_minutes"] = 10
        due = datetime(2026, 11, 25, 5, 50, tzinfo=timezone(timedelta(hours=8)))  # Wed, winter rest 06:00
        with patch.object(self.w, "_start_rest_close_countdown") as countdown:
            self.w._check_rest_close(due - timedelta(minutes=1))
            self.w._check_rest_close(due + timedelta(seconds=10))
            self.w._check_rest_close(due + timedelta(seconds=40))
            self.w._check_rest_close(due + timedelta(minutes=5))
        countdown.assert_called_once()
        self.w.store.data["ui"]["rest_close_enabled"] = False


if __name__ == "__main__":
    unittest.main()


class Mt5CloseReadbackTests(unittest.TestCase):
    def run_close(self, reads):
        reads = iter(reads)
        with patch.object(close_both, "open_mt5_context"), \
             patch.object(close_both, "hover_mt5_bulk_actions"), \
             patch.object(close_both, "find_mt5_menu_item", return_value=(10, 10, 50, 30)), \
             patch.object(close_both, "last_mt5_match_enabled", return_value=True), \
             patch.object(close_both.time, "sleep"), \
             patch.object(close_both.time, "monotonic", side_effect=itertools.count(0, 0.5)):
            return close_both.close_mt5(Mock(), "main", {"position_order_row": {"x": 1}}, lambda h: 1,
                                        Abort(), lambda x, y: None, lambda k: None,
                                        read_positions=lambda: next(reads))

    def test_empty_position_list_confirms_the_close(self):
        self.assertIn("已平倉", self.run_close([("p1",), ()]))

    def test_positions_still_open_are_reported(self):
        self.assertIn("還讀到 2 筆", self.run_close([("p1", "p2")] * 100))
