import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from momentum_pact.demo import build_demo_data


class DemoDataTests(unittest.TestCase):
    def test_demo_covers_dashboard_categories_and_feature_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.fromisoformat("2026-08-18T12:00-06:00")
            store = build_demo_data(Path(directory) / "demo.json", now=now)
            snapshot = store.snapshot(now)

        commitments = {
            item["title"]: item
            for item in store.commitments(include_closed=True, now=now)
        }
        expected_states = {
            "Renew library books": "overdue",
            "Choose meals for the week": "due_soon",
            "Schedule an annual appointment": "check_in_due",
            "Buy groceries": "in_progress",
            "Check the weekend weather": "planned",
            "Take out the recycling": "completed",
            "Organize a spare drawer": "triaged",
        }
        self.assertEqual(
            {
                title: commitments[title]["display_status"]
                for title in expected_states
            },
            expected_states,
        )
        self.assertEqual(snapshot["counts"]["overdue"], 1)
        self.assertEqual(snapshot["counts"]["due_soon"], 1)
        self.assertEqual(snapshot["counts"]["check_in_due"], 1)
        self.assertEqual(snapshot["counts"]["completed"], 1)
        self.assertEqual(
            {goal["status"] for goal in store.data["goals"]},
            {"active", "paused", "achieved"},
        )
        self.assertGreaterEqual(len(store.data["goal_revisions"]), 3)
        self.assertEqual(
            {entry["state"] for entry in store.data["check_ins"]},
            {"on_track", "at_risk", "blocked", "done"},
        )
        self.assertEqual(
            {item["priority"] for item in store.data["commitments"]},
            {"low", "medium", "high"},
        )
        self.assertEqual(
            {
                dependency["kind"]
                for item in store.data["commitments"]
                for dependency in item["dependencies"]
            },
            {"required", "helpful"},
        )
        groceries = commitments["Buy groceries"]
        self.assertEqual(
            {item["kind"] for item in groceries["dependencies"]},
            {"required", "helpful"},
        )
        self.assertEqual(
            store.commitment_progress(commitments["Choose meals for the week"]["id"])[
                "completed"
            ],
            1,
        )
        self.assertTrue(
            store.commitment_progress(commitments["Take out the recycling"]["id"])[
                "all_met"
            ]
        )
        self.assertTrue(any(item.get("goal_id") for item in commitments.values()))
        self.assertTrue(any(not item.get("goal_id") for item in commitments.values()))
        self.assertTrue(any(item.get("notes") for item in commitments.values()))
        archived = [
            item for item in store.data["commitments"] if item.get("archived_at")
        ]
        self.assertEqual([item["title"] for item in archived], ["Return a borrowed item"])
        self.assertNotIn("Return a borrowed item", commitments)


if __name__ == "__main__":
    unittest.main()
