"""Offline URL-to-worksheet selection tests; no Google API calls."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.sheets import (
    SheetReader, _csv_export_url, spreadsheet_gid_from_url,
)


class SpreadsheetUrlGidTests(unittest.TestCase):
    def test_reads_gid_from_query_or_fragment(self):
        self.assertEqual(
            spreadsheet_gid_from_url(
                "https://docs.google.com/spreadsheets/d/book/edit?gid=1234"
            ),
            "1234",
        )
        self.assertEqual(
            spreadsheet_gid_from_url(
                "https://docs.google.com/spreadsheets/d/book/edit#gid=5678"
            ),
            "5678",
        )
        self.assertEqual(
            spreadsheet_gid_from_url(
                "https://docs.google.com/spreadsheets/d/book/edit#gid=not-a-number"
            ),
            "",
        )

    def test_csv_export_uses_gid_in_url_before_legacy_setting(self):
        self.assertEqual(
            _csv_export_url(
                "https://docs.google.com/spreadsheets/d/book/edit#gid=5678",
                "1234",
            ),
            "https://docs.google.com/spreadsheets/d/book/export?format=csv&gid=5678",
        )

    def test_service_account_selects_worksheet_gid_from_url(self):
        worksheet = object()
        spreadsheet = MagicMock()
        spreadsheet.get_worksheet_by_id.return_value = worksheet
        client = MagicMock()
        client.open_by_url.return_value = spreadsheet
        gspread = SimpleNamespace(service_account=MagicMock(return_value=client))
        config = {
            "service_account_file": "offline-test.json",
            "spreadsheet_url": (
                "https://docs.google.com/spreadsheets/d/book/edit#gid=1745982444"
            ),
            "worksheet": "Old tab name",
        }

        with patch.dict(sys.modules, {"gspread": gspread}):
            found = SheetReader()._open_gspread_worksheet(config)

        self.assertIs(found, worksheet)
        spreadsheet.get_worksheet_by_id.assert_called_once_with(1745982444)
        spreadsheet.worksheet.assert_not_called()

    def test_internal_supplementary_tab_can_override_url_gid_by_name(self):
        worksheet = object()
        spreadsheet = MagicMock()
        spreadsheet.worksheet.return_value = worksheet
        client = MagicMock()
        client.open_by_url.return_value = spreadsheet
        gspread = SimpleNamespace(service_account=MagicMock(return_value=client))
        config = {
            "service_account_file": "offline-test.json",
            "spreadsheet_url": (
                "https://docs.google.com/spreadsheets/d/book/edit#gid=1745982444"
            ),
            "worksheet": "Progress tab",
            "_worksheet_name_override": True,
        }

        with patch.dict(sys.modules, {"gspread": gspread}):
            found = SheetReader()._open_gspread_worksheet(config)

        self.assertIs(found, worksheet)
        spreadsheet.worksheet.assert_called_once_with("Progress tab")
        spreadsheet.get_worksheet_by_id.assert_not_called()


if __name__ == "__main__":
    unittest.main()
