"""Phone progress card for 「填入兩邊」: display only, from existing milestones."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from trading_helper import fill_progress
from trading_helper.auto_entry import AutoEntryJournal
from trading_helper.remote_ui import RemoteController


class FillProgressTests(unittest.TestCase):
    def test_journal_milestones_reach_listeners(self):
        seen = []
        fill_progress.add_listener(seen.append)
        self.addCleanup(fill_progress.remove_listener, seen.append)
        with tempfile.TemporaryDirectory() as folder:
            journal = AutoEntryJournal(Path(folder) / "journal.json")
            journal.record("k", "prepared", "")
            journal.record("k", "filled_internal", "ticket=1")
            journal.record("k", "filled_external", "ticket=2")
            journal.record("k", "synchronized", "1/2")
        self.assertEqual(seen, ["entered_internal", "entered_external", "synced"])

    def test_steps_follow_the_options_and_mark_what_is_done(self):
        controller = SimpleNamespace(active={"action": "fill_both"}, _fill_steps=None)
        controller._fill_steps = {"done": frozenset(), "entry": True, "sync": True}
        RemoteController._fill_step(controller, "form_internal")
        RemoteController._fill_step(controller, "form_external")
        RemoteController._fill_step(controller, "entered_internal")
        steps = RemoteController._fill_progress(controller)
        self.assertEqual([s["label"] for s in steps],
                         ["場內填寫", "場外填寫", "場內進場", "場外進場", "同步場外 SL／TP"])
        self.assertEqual([s["done"] for s in steps], [True, True, True, False, False])
        # Fill only (no auto entry): just the two forms.
        controller._fill_steps = {"done": frozenset(), "entry": False, "sync": False}
        self.assertEqual(len(RemoteController._fill_progress(controller)), 2)
        # Nothing shown for other actions or once the operation is over.
        controller.active = None
        self.assertIsNone(RemoteController._fill_progress(controller))


if __name__ == "__main__":
    unittest.main()
