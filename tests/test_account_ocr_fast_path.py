"""Bound-account OCR early exit: exact match only, offline and read-only."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.windows import WindowController, WindowInfo


class AccountOCRFastPathTests(unittest.TestCase):
    def setUp(self):
        self.controller = WindowController(SimpleNamespace(guard=lambda: None))
        self.window = WindowInfo(123, "cTrader Demo", 10, 20, 1210, 820)
        self.controller.focus = MagicMock(return_value=self.window)
        self.controller._validate_calibrated_window = MagicMock()
        self.controller.screen_point = MagicMock(return_value=(300, 100))
        self.point = {"x_px": 290, "y_px": 80, "window_width": 1200,
                      "window_height": 800}

    def test_exact_bound_account_returns_on_first_crop(self):
        with patch.object(
            self.controller,
            "_read_text_candidates_ocr",
            return_value=["11111111"],
        ) as read_ocr:
            account = self.controller.read_account_number(
                self.window, self.point, expected_digits="11111111"
            )

        self.assertEqual(account, "11111111")
        read_ocr.assert_called_once()
        self.assertEqual(read_ocr.call_args.kwargs["expected_digits"], "11111111")

    def test_account_mismatch_still_checks_all_crops_and_returns_detected_value(self):
        with patch.object(
            self.controller,
            "_read_text_candidates_ocr",
            side_effect=[["1234"], ["5678"], ["5678"]],
        ) as read_ocr:
            account = self.controller.read_account_number(
                self.window, self.point, expected_digits="0000"
            )

        self.assertEqual(account, "1234")
        self.assertEqual(read_ocr.call_count, 3)


if __name__ == "__main__":
    unittest.main()
