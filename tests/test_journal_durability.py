"""Journal write safety checks using temporary files only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_helper.auto_entry import AutoEntryJournal


class JournalDurabilityTests(unittest.TestCase):
    def test_write_flushes_and_fsyncs_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"journal.json"
            journal=AutoEntryJournal(target)
            with patch("trading_helper.auto_entry.os.fsync") as fsync:
                journal._write({"attempt":{"status":"prepared"}})
            fsync.assert_called_once()
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"attempt":{"status":"prepared"}},
            )

    def test_fsync_failure_preserves_last_confirmed_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"journal.json"
            target.write_text('{"attempt":{"status":"filled"}}',
                              encoding="utf-8")
            journal=AutoEntryJournal(target)
            with patch("trading_helper.auto_entry.os.fsync",
                       side_effect=OSError("simulated disk error")):
                with self.assertRaises(OSError):
                    journal._write({"attempt":{"status":"prepared"}})
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"attempt":{"status":"filled"}},
            )


if __name__=="__main__":
    unittest.main()
