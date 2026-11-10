from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import URLError

from trading_helper import update_check


class UpdateCheckTests(unittest.TestCase):
    def test_newer_github_version_returns_notice_for_lab_page(self):
        notice = update_check.check_for_update("0.1.0", "0.1.1")

        self.assertIsNotNone(notice)
        self.assertEqual(notice.current_version, "0.1.0")
        self.assertEqual(notice.latest_version, "0.1.1")
        self.assertIn("lab/2026-10-16-safe-defaults-preflight", notice.page_url)

    def test_same_or_older_version_does_not_show_notice(self):
        self.assertIsNone(update_check.check_for_update("0.1.1", "0.1.1"))
        self.assertIsNone(update_check.check_for_update("0.1.1", "0.1.0"))

    def test_invalid_version_does_not_show_notice(self):
        self.assertIsNone(update_check.check_for_update("dev", "0.2.0"))
        self.assertIsNone(update_check.check_for_update("0.1.0", "main"))

    def test_network_failure_is_silent(self):
        with patch.object(update_check, "urlopen", side_effect=URLError("offline")):
            self.assertIsNone(update_check.fetch_latest_version())

    def test_fetch_reads_the_version_from_the_lab_source(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'__version__ = "2.3.4"\n'

        with patch.object(update_check, "urlopen", return_value=Response()) as open_url:
            self.assertEqual(update_check.fetch_latest_version(), "2.3.4")
        self.assertIn("2026-10-16-safe-defaults-preflight", open_url.call_args.args[0].full_url)


if __name__ == "__main__":
    unittest.main()
