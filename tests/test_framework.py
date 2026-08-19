import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_pact.framework import (
    AccountabilityError,
    AccountabilityStore,
    classify_commitment,
    format_countdown,
    format_due_in,
    parse_datetime,
)


class AccountabilityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name) / "accountability.json"
        self.store = AccountabilityStore(self.data_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_successful_save_notifies_integrations(self):
        notifications: list[str] = []
        store = AccountabilityStore(
            self.data_path, on_save=lambda: notifications.append("saved")
        )

        store.add_commitment("Notify Waybar", "2026-08-20 12:00")

        self.assertEqual(notifications, ["saved"])

    def test_creates_goal_and_commitment_and_persists_them(self):
        goal = self.store.add_goal(
            "Finish a portfolio", why="Make recent work visible", target_date="2027-01-31"
        )
        item = self.store.add_commitment(
            "Choose three projects",
            due_at="2026-09-01 17:00",
            goal_id=goal["id"],
            win_conditions=["Three project names are written down"],
            check_in_at="2026-08-20 18:00",
        )

        reloaded = AccountabilityStore(self.data_path)
        self.assertEqual(reloaded.goal(goal["id"])["title"], "Finish a portfolio")
        self.assertEqual(reloaded.commitment(item["id"])["goal_id"], goal["id"])
        self.assertNotIn("win_conditions", reloaded.goal(goal["id"]))
        self.assertEqual(
            reloaded.commitment(item["id"])["win_conditions"][0]["text"],
            "Three project names are written down",
        )
        self.assertEqual(len(reloaded.data["activity"]), 2)

    def test_snapshot_distinguishes_overdue_due_soon_and_check_in_due(self):
        now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        overdue = self.store.add_commitment("Late", "2026-08-12T12:00+00:00")
        due_soon = self.store.add_commitment("Soon", "2026-08-14T11:59:59+00:00")
        boundary = self.store.add_commitment("Later", "2026-08-14T12:00+00:00")
        check_in = self.store.add_commitment(
            "Review me",
            "2026-08-20T18:00+00:00",
            check_in_at="2026-08-13T11:00+00:00",
        )

        self.assertEqual(classify_commitment(overdue, now), "overdue")
        self.assertEqual(classify_commitment(due_soon, now), "due_soon")
        self.assertEqual(classify_commitment(boundary, now), "planned")
        self.assertEqual(classify_commitment(check_in, now), "check_in_due")
        counts = self.store.snapshot(now)["counts"]
        self.assertEqual(counts["overdue"], 1)
        self.assertEqual(counts["due_soon"], 1)
        self.assertEqual(counts["check_in_due"], 1)

    def test_due_in_omits_status_already_shown_by_the_overview(self):
        now = datetime(2026, 8, 18, 18, 0, tzinfo=timezone.utc)
        overdue = {"status": "planned", "due_at": "2026-08-18T17:00+00:00"}

        self.assertEqual(format_countdown(overdue, now), "OVERDUE · 0:01:00:00")
        self.assertEqual(format_due_in(overdue, now), "0:01:00:00")

    def test_check_in_advances_commitment_and_keeps_history(self):
        item = self.store.add_commitment("Draft outline", "2026-09-01 12:00")
        check_in = self.store.record_check_in(
            item["id"],
            state="at_risk",
            note="I underestimated the research",
            next_action="Collect the three missing sources",
            next_check_in_at="2026-08-14 20:00",
        )

        updated = self.store.commitment(item["id"])
        self.assertEqual(updated["status"], "in_progress")
        self.assertEqual(self.store.check_ins_for(item["id"])[0]["id"], check_in["id"])
        self.assertEqual(updated["check_in_at"], "2026-08-14T20:00-06:00")

    def test_done_check_in_completes_commitment(self):
        item = self.store.add_commitment("Submit form", "2026-09-01 12:00")
        self.store.record_check_in(item["id"], state="done", note="Confirmation received")

        updated = self.store.commitment(item["id"])
        self.assertEqual(updated["status"], "completed")
        self.assertIsNotNone(updated["completed_at"])

    def test_invalid_goal_reference_is_rejected(self):
        with self.assertRaises(AccountabilityError):
            self.store.add_commitment(
                "Impossible link", "2026-09-01 12:00", goal_id="goal_missing"
            )

    def test_goal_revision_updates_goal_and_preserves_history(self):
        goal = self.store.add_goal(
            "Pass the course", why="Finish the requirement", target_date="2026-12-18"
        )
        created_at = goal["created_at"]
        revision = self.store.revise_goal(
            goal["id"],
            title="Earn a strong course result",
            why="Build durable understanding, not merely pass",
            target_date="2026-12-20",
            status="active",
            reason="The original outcome was too narrowly framed.",
        )

        updated = self.store.goal(goal["id"])
        self.assertEqual(updated["title"], "Earn a strong course result")
        self.assertEqual(updated["created_at"], created_at)
        self.assertEqual(revision["before"]["title"], "Pass the course")
        self.assertEqual(revision["after"]["target_date"], "2026-12-20")
        self.assertIn("title", revision["changes"])
        self.assertEqual(
            self.store.goal_revisions_for(goal["id"])[0]["id"], revision["id"]
        )

    def test_goal_revision_requires_a_reason_and_an_actual_change(self):
        goal = self.store.add_goal("Finish project", why="Ship it")
        with self.assertRaises(AccountabilityError):
            self.store.revise_goal(
                goal["id"], "Finish project", "Ship it", None, "active", ""
            )
        with self.assertRaises(AccountabilityError):
            self.store.revise_goal(
                goal["id"],
                "Finish project",
                "Ship it",
                None,
                "active",
                "Reconsidered it",
            )

    def test_win_conditions_track_commitment_progress_and_completion_time(self):
        goal = self.store.add_goal("Publish portfolio")
        commitment = self.store.add_commitment(
            "Launch portfolio",
            "2026-09-01 17:00",
            goal_id=goal["id"],
        )
        first = self.store.add_win_condition(
            commitment["id"], "Three projects are documented"
        )
        self.store.add_win_condition(
            commitment["id"], "The site is publicly accessible"
        )

        initial = self.store.commitment_progress(commitment["id"])
        self.assertEqual(initial["completed"], 0)
        self.assertEqual(initial["total"], 2)
        self.assertFalse(initial["all_met"])

        completed = self.store.set_win_condition(
            commitment["id"], first["id"], True
        )
        self.assertTrue(completed["completed"])
        self.assertIsNotNone(completed["completed_at"])
        self.assertEqual(
            self.store.commitment_progress(commitment["id"])["ratio"], 0.5
        )

        reopened = self.store.set_win_condition(
            commitment["id"], first["id"], False
        )
        self.assertFalse(reopened["completed"])
        self.assertIsNone(reopened["completed_at"])

    def test_win_conditions_reject_duplicates_and_unknown_ids(self):
        commitment = self.store.add_commitment(
            "Complete capstone", "2026-09-01 17:00"
        )
        self.store.add_win_condition(
            commitment["id"], "Final demonstration is delivered"
        )
        with self.assertRaises(AccountabilityError):
            self.store.add_win_condition(
                commitment["id"], " final DEMONSTRATION is delivered "
            )
        with self.assertRaises(AccountabilityError):
            self.store.set_win_condition(
                commitment["id"], "condition_missing", True
            )
        with self.assertRaises(AccountabilityError):
            self.store.add_commitment(
                "Duplicated plan",
                "2026-09-02 17:00",
                win_conditions=["Write outline", " write OUTLINE "],
            )

    def test_win_conditions_can_be_removed_after_creation(self):
        commitment = self.store.add_commitment(
            "Prepare presentation",
            "2026-09-02 17:00",
            win_conditions=["Draft slides", "Rehearse twice"],
        )
        condition_id = commitment["win_conditions"][0]["id"]
        removed = self.store.remove_win_condition(commitment["id"], condition_id)

        self.assertEqual(removed["text"], "Draft slides")
        self.assertEqual(self.store.commitment_progress(commitment["id"])["total"], 1)
        self.assertEqual(self.store.data["activity"][-1]["kind"], "win_condition_removed")
        with self.assertRaises(AccountabilityError):
            self.store.remove_win_condition(commitment["id"], condition_id)

    def test_dependencies_are_advisory_and_preserve_their_kind(self):
        prerequisite = self.store.add_commitment(
            "Pay outstanding balance", "2026-08-18 17:00"
        )
        dependent = self.store.add_commitment(
            "Register for courses", "2026-08-19 17:00"
        )

        relationship = self.store.add_dependency(
            dependent["id"], prerequisite["id"], "required"
        )
        self.store.set_commitment_status(dependent["id"], "completed")

        self.assertEqual(relationship["kind"], "required")
        self.assertEqual(
            self.store.dependencies_for(dependent["id"])[0]["title"],
            "Pay outstanding balance",
        )
        self.assertEqual(
            self.store.dependents_for(prerequisite["id"])[0]["title"],
            "Register for courses",
        )
        self.assertEqual(
            self.store.commitment(prerequisite["id"])["status"], "planned"
        )

    def test_dependencies_reject_duplicates_self_links_and_cycles(self):
        first = self.store.add_commitment("First", "2026-09-01 12:00")
        second = self.store.add_commitment("Second", "2026-09-02 12:00")
        third = self.store.add_commitment("Third", "2026-09-03 12:00")

        self.store.add_dependency(second["id"], first["id"], "helpful")
        self.store.add_dependency(third["id"], second["id"], "required")
        with self.assertRaises(AccountabilityError):
            self.store.add_dependency(second["id"], first["id"], "required")
        with self.assertRaises(AccountabilityError):
            self.store.add_dependency(first["id"], first["id"])
        with self.assertRaises(AccountabilityError):
            self.store.add_dependency(first["id"], third["id"])

        self.assertEqual(self.store.commitment(first["id"])["dependencies"], [])

    def test_dependencies_can_be_removed_and_record_history(self):
        prerequisite = self.store.add_commitment("Prerequisite", "2026-09-01 12:00")
        dependent = self.store.add_commitment("Dependent", "2026-09-02 12:00")
        self.store.add_dependency(dependent["id"], prerequisite["id"])

        removed = self.store.remove_dependency(dependent["id"], prerequisite["id"])

        self.assertEqual(removed["commitment_id"], prerequisite["id"])
        self.assertEqual(self.store.commitment(dependent["id"])["dependencies"], [])
        self.assertEqual(self.store.data["activity"][-1]["kind"], "dependency_unlinked")

    def test_delete_commitment_clears_check_ins_and_dependency_references(self):
        prerequisite = self.store.add_commitment(
            "Prerequisite", "2026-09-01 12:00"
        )
        target = self.store.add_commitment("Mistake", "2026-09-02 12:00")
        dependent = self.store.add_commitment("Dependent", "2026-09-03 12:00")
        self.store.add_dependency(target["id"], prerequisite["id"])
        self.store.add_dependency(dependent["id"], target["id"])
        self.store.record_check_in(target["id"], "on_track")

        removed = self.store.delete_commitment(target["id"])

        self.assertEqual(removed["title"], "Mistake")
        with self.assertRaises(AccountabilityError):
            self.store.commitment(target["id"])
        self.assertFalse(
            any(
                item["commitment_id"] == target["id"]
                for item in self.store.data["check_ins"]
            )
        )
        self.assertEqual(self.store.dependencies_for(dependent["id"]), [])
        self.assertEqual(
            self.store.data["activity"][-1]["kind"], "commitment_deleted"
        )

    def test_closed_commitments_can_be_archived_and_restored(self):
        completed = self.store.add_commitment("Finished", "2026-09-01 12:00")
        triaged = self.store.add_commitment("Not pursuing", "2026-09-02 12:00")
        open_item = self.store.add_commitment("Still open", "2026-09-03 12:00")
        self.store.set_commitment_status(completed["id"], "completed")
        self.store.set_commitment_status(triaged["id"], "triaged")

        self.store.archive_commitment(completed["id"])
        self.store.archive_commitment(triaged["id"])

        visible_ids = {
            item["id"] for item in self.store.commitments(include_closed=True)
        }
        archived_ids = {
            item["id"]
            for item in self.store.commitments(
                include_closed=True, include_archived=True
            )
            if item.get("archived_at")
        }
        self.assertNotIn(completed["id"], visible_ids)
        self.assertNotIn(triaged["id"], visible_ids)
        self.assertEqual(archived_ids, {completed["id"], triaged["id"]})
        self.assertNotIn(open_item["id"], archived_ids)
        self.assertEqual(self.store.snapshot()["counts"]["completed"], 0)
        with self.assertRaises(AccountabilityError):
            self.store.archive_commitment(open_item["id"])

        restored = self.store.restore_commitment(triaged["id"])
        self.assertIsNone(restored["archived_at"])
        self.assertEqual(restored["status"], "triaged")

    def test_legacy_skipped_status_migrates_to_triaged(self):
        item = self.store.add_commitment("Old decision", "2026-09-01 12:00")
        self.store.data["commitments"][0]["status"] = "skipped"
        self.data_path.write_text(json.dumps(self.store.data), encoding="utf-8")

        migrated = AccountabilityStore(self.data_path).commitment(item["id"])

        self.assertEqual(migrated["status"], "triaged")
        self.assertIsNone(migrated["archived_at"])

    def test_commitment_can_be_linked_changed_and_unlinked_retroactively(self):
        first_goal = self.store.add_goal("Finish the semester")
        second_goal = self.store.add_goal("Master linear algebra")
        commitment = self.store.add_commitment(
            "Complete problem set",
            "2026-09-02 17:00",
            win_conditions=["Solve every question"],
        )

        linked = self.store.set_commitment_goal(commitment["id"], first_goal["id"])
        self.assertEqual(linked["goal_id"], first_goal["id"])
        changed = self.store.set_commitment_goal(commitment["id"], second_goal["id"])
        self.assertEqual(changed["goal_id"], second_goal["id"])
        unlinked = self.store.set_commitment_goal(commitment["id"], None)
        self.assertIsNone(unlinked["goal_id"])
        self.assertEqual(
            [entry["kind"] for entry in self.store.data["activity"][-3:]],
            [
                "commitment_goal_linked",
                "commitment_goal_changed",
                "commitment_goal_unlinked",
            ],
        )
        with self.assertRaises(AccountabilityError):
            self.store.set_commitment_goal(commitment["id"], "goal_missing")

    def test_review_is_readable_markdown(self):
        self.store.add_commitment(
            "Publish draft",
            "2026-09-01 12:00",
            win_conditions=["A public URL exists"],
            why="Create momentum",
        )
        review = self.store.review_markdown(
            datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        )
        self.assertIn("# Accountability snapshot", review)
        self.assertIn("### Publish draft", review)
        self.assertIn("A public URL exists", review)

    def test_malformed_data_is_rejected(self):
        self.data_path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        with self.assertRaises(AccountabilityError):
            AccountabilityStore(self.data_path)

    def test_wall_clock_dates_use_the_local_offset_for_that_date(self):
        winter = datetime(2025, 11, 12, 23, 59)
        self.assertEqual(
            parse_datetime("2025-11-12 23:59").utcoffset(),
            winter.astimezone().utcoffset(),
        )

    def test_countdown_preserves_original_day_hour_minute_second_format(self):
        now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
        future = {
            "status": "planned",
            "due_at": "2026-08-14T14:03:04+00:00",
        }
        overdue = {
            "status": "in_progress",
            "due_at": "2026-08-13T10:59:59+00:00",
        }
        self.assertEqual(format_countdown(future, now), "1:02:03:04")
        self.assertEqual(format_countdown(overdue, now), "OVERDUE · 0:01:00:01")

    def test_countdown_uses_terminal_status_labels(self):
        now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(format_countdown({"status": "completed"}, now), "COMPLETED")
        self.assertEqual(format_countdown({"status": "triaged"}, now), "TRIAGED")


if __name__ == "__main__":
    unittest.main()
