"""LAB journal regression: never claim an order barrier was persisted pre-flush."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_helper.auto_entry import AutoEntryJournal


class JournalDurabilityTests(unittest.TestCase):
    def test_fsync_happens_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = AutoEntryJournal(Path(folder) / "journal.json")
            calls = []
            actual_fsync = os.fsync
            actual_replace = os.replace

            def flush(fd):
                calls.append("fsync")
                return actual_fsync(fd)

            def rename(source, destination):
                calls.append("replace")
                return actual_replace(source, destination)

            with patch("trading_helper.auto_entry.os.fsync", side_effect=flush), \
                 patch("trading_helper.auto_entry.os.replace", side_effect=rename):
                journal.record("once", "sending_internal", "Demo pending")

            self.assertEqual(calls, ["fsync", "replace"])
            self.assertEqual(journal.status("once"), "sending_internal")

    def test_failed_flush_leaves_last_committed_entry_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = AutoEntryJournal(Path(folder) / "journal.json")
            journal.record("once", "prepared", "both checked")
            committed = journal.path.read_bytes()
            with patch("trading_helper.auto_entry.os.fsync",
                       side_effect=OSError("simulated disk write error")):
                with self.assertRaises(OSError):
                    journal.record("once", "sending_external", "pending")
            self.assertEqual(journal.path.read_bytes(), committed)
            self.assertEqual(journal.status("once"), "prepared")


if __name__ == "__main__":
    unittest.main()
