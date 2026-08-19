import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

from momentum_pact.framework import AccountabilityStore
from momentum_pact.integrations.waybar import (
    main,
    watch_waybar_payloads,
    waybar_payload,
)


class WaybarPayloadTests(unittest.TestCase):
    def test_watcher_emits_only_after_data_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "accountability.json"
            store = AccountabilityStore(data_path)
            store.save()
            payloads = watch_waybar_payloads(data_path, poll_interval=0)

            self.assertEqual(next(payloads)["class"], "clear")
            store.add_commitment("New item", "2099-08-20 12:00")

            updated = next(payloads)

        self.assertEqual(updated["class"], "active")
        self.assertIn("1", updated["text"])

    def test_completed_overdue_commitment_clears_urgency(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AccountabilityStore(Path(directory) / "accountability.json")
            commitment = store.add_commitment(
                "Was overdue", "2026-08-17 12:00"
            )
            store.set_commitment_status(commitment["id"], "completed")
            snapshot = store.snapshot(datetime.fromisoformat("2026-08-18T12:00-06:00"))

        payload = waybar_payload(snapshot)
        self.assertEqual(snapshot["counts"]["overdue"], 0)
        self.assertEqual(snapshot["counts"]["active"], 0)
        self.assertEqual(payload["class"], "clear")

    def test_submitted_check_in_clears_check_in_due_urgency(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AccountabilityStore(Path(directory) / "accountability.json")
            commitment = store.add_commitment(
                "Check in",
                "2026-08-20 12:00",
                check_in_at="2026-08-18 09:00",
            )
            now = datetime.fromisoformat("2026-08-18T12:00-06:00")
            self.assertEqual(waybar_payload(store.snapshot(now))["class"], "check-in-due")

            store.record_check_in(
                commitment["id"],
                "on_track",
                next_check_in_at="2026-08-19 09:00",
            )
            payload = waybar_payload(store.snapshot(now))

        self.assertEqual(payload["class"], "active")

    def test_overdue_state_takes_visual_precedence(self):
        payload = waybar_payload(
            {
                "counts": {
                    "active": 4,
                    "overdue": 1,
                    "due_soon": 1,
                    "check_in_due": 1,
                    "completed": 0,
                },
                "items": [],
            }
        )

        self.assertEqual(payload["class"], "overdue")
        self.assertIn('<span foreground="#ff4057">󰅚 1</span>', payload["text"])
        self.assertIn('<span foreground="#ffd166">󰃰 1</span>', payload["text"])
        self.assertIn('<span foreground="#c99cff">󰍴 1</span>', payload["text"])
        self.assertIn('<span foreground="#66c2ff">󰄉 1</span>', payload["text"])
        self.assertIn("4 open", payload["tooltip"])

    def test_status_counters_do_not_double_count_open_commitments(self):
        payload = waybar_payload(
            {
                "counts": {
                    "active": 3,
                    "overdue": 1,
                    "due_soon": 0,
                    "check_in_due": 0,
                    "completed": 0,
                },
                "items": [],
            }
        )

        self.assertIn('<span foreground="#ff4057">󰅚 1</span>', payload["text"])
        self.assertIn('<span foreground="#66c2ff">󰄉 2</span>', payload["text"])
        self.assertNotIn("󰄉 3", payload["text"])

    def test_tooltip_escapes_commitment_titles_for_pango(self):
        payload = waybar_payload(
            {
                "counts": {
                    "active": 1,
                    "overdue": 0,
                    "due_soon": 1,
                    "check_in_due": 0,
                    "completed": 0,
                },
                "items": [
                    {
                        "title": "Read <chapter> & notes",
                        "display_status": "due_soon",
                        "due_at": "2026-08-18T20:00:00-06:00",
                    }
                ],
            }
        )

        self.assertIn("Read &lt;chapter&gt; &amp; notes", payload["tooltip"])

    def test_cli_emits_valid_json_for_an_empty_store(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "accountability.json"
            AccountabilityStore(data_path).save()
            output = StringIO()
            with redirect_stdout(output):
                result = main(["--data", str(data_path)])

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["class"], "clear")
        self.assertIn("clear", payload["text"])

    def test_cli_keeps_module_visible_when_data_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "accountability.json"
            data_path.write_text("not json", encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                result = main(["--data", str(data_path)])

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["class"], "error")


if __name__ == "__main__":
    unittest.main()
