from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
OPEN_STATUSES = {"planned", "in_progress"}
TERMINAL_STATUSES = {"completed", "triaged"}
COMMITMENT_STATUSES = OPEN_STATUSES | TERMINAL_STATUSES
CHECK_IN_STATES = {"on_track", "at_risk", "blocked", "done"}
PRIORITIES = {"low", "medium", "high"}
GOAL_STATUSES = {"active", "paused", "achieved"}
DEPENDENCY_KINDS = {"required", "helpful"}


class AccountabilityError(ValueError):
    """Raised when accountability data or a requested operation is invalid."""


def default_data() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "display_name": "",
        },
        "goals": [],
        "goal_revisions": [],
        "commitments": [],
        "check_ins": [],
        "activity": [],
    }


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def parse_datetime(value: str | None) -> datetime | None:
    if value is None or not str(value).strip():
        return None

    cleaned = str(value).strip()
    parsed: datetime | None = None
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(cleaned, pattern)
            break
        except ValueError:
            continue

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError as exc:
            raise AccountabilityError(
                f"Invalid date/time '{value}'. Use YYYY-MM-DD HH:MM."
            ) from exc

    if parsed.tzinfo is None:
        # Interpret wall-clock input in the machine's local zone on that date.
        # astimezone() preserves historical/future daylight-saving offsets.
        parsed = parsed.astimezone()
    return parsed


def normalize_datetime(value: str | None) -> str | None:
    parsed = parse_datetime(value)
    return parsed.isoformat(timespec="minutes") if parsed else None


def parse_date(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise AccountabilityError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def classify_commitment(
    commitment: dict[str, Any], now: datetime | None = None
) -> str:
    status = commitment.get("status", "planned")
    if status == "completed":
        return "completed"
    if status == "triaged":
        return "triaged"

    current = now or now_local()
    due = parse_datetime(commitment.get("due_at"))
    check_in = parse_datetime(commitment.get("check_in_at"))
    if due and due < current:
        return "overdue"
    if check_in and check_in <= current:
        return "check_in_due"
    if due and (due - current).total_seconds() < 24 * 60 * 60:
        return "due_soon"
    return status


def format_when(value: str | None) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return "—"
    return parsed.astimezone().strftime("%a %b %d, %Y · %I:%M %p")


def format_countdown(
    commitment: dict[str, Any], now: datetime | None = None
) -> str:
    status = commitment.get("status", "planned")
    if status == "completed":
        return "COMPLETED"
    if status == "triaged":
        return "TRIAGED"

    due = parse_datetime(commitment.get("due_at"))
    if due is None:
        return "NO DEADLINE"
    current = now or now_local()
    total_seconds = int((due - current).total_seconds())
    overdue = total_seconds < 0
    remaining = abs(total_seconds)
    days, remainder = divmod(remaining, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    clock = f"{days}:{hours:02}:{minutes:02}:{seconds:02}"
    return f"OVERDUE · {clock}" if overdue else clock


def format_due_in(
    commitment: dict[str, Any], now: datetime | None = None
) -> str:
    """Format only temporal distance; the overview's State column owns status."""
    countdown = format_countdown(commitment, now)
    return countdown.removeprefix("OVERDUE · ")


class AccountabilityStore:
    """Validated JSON storage for goals, commitments, check-ins, and history."""

    def __init__(
        self, path: str | Path, on_save: Callable[[], None] | None = None
    ):
        self.path = Path(path)
        self.on_save = on_save
        self.data: dict[str, Any] = default_data()
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.data = default_data()
            return self.data
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AccountabilityError(f"Could not read {self.path}: {exc}") from exc
        if self.data.get("schema_version") == SCHEMA_VERSION:
            self.data.setdefault("goal_revisions", [])
            if isinstance(self.data.get("commitments"), list):
                for commitment in self.data["commitments"]:
                    if isinstance(commitment, dict):
                        if commitment.get("status") == "skipped":
                            commitment["status"] = "triaged"
                        commitment.setdefault("win_conditions", [])
                        commitment.setdefault("dependencies", [])
                        commitment.setdefault("archived_at", None)
        self.validate()
        return self.data

    def validate(self) -> None:
        data = self.data
        if data.get("schema_version") != SCHEMA_VERSION:
            raise AccountabilityError(
                f"Expected schema version {SCHEMA_VERSION}; "
                f"found {data.get('schema_version')!r}."
            )

        for section in (
            "goals",
            "goal_revisions",
            "commitments",
            "check_ins",
            "activity",
        ):
            if not isinstance(data.get(section), list):
                raise AccountabilityError(f"'{section}' must be a list.")

        goals = {goal.get("id") for goal in data["goals"]}
        if None in goals or len(goals) != len(data["goals"]):
            raise AccountabilityError("Every goal needs a unique id.")
        for goal in data["goals"]:
            if not str(goal.get("title", "")).strip():
                raise AccountabilityError(f"Goal {goal.get('id')} needs a title.")
            if goal.get("status") not in GOAL_STATUSES:
                raise AccountabilityError(f"Goal {goal.get('id')} has an invalid status.")
            parse_date(goal.get("target_date"))

        revision_ids: set[str] = set()
        for revision in data["goal_revisions"]:
            revision_id = revision.get("id")
            if not revision_id or revision_id in revision_ids:
                raise AccountabilityError("Every goal revision needs a unique id.")
            revision_ids.add(revision_id)
            if revision.get("goal_id") not in goals:
                raise AccountabilityError("A goal revision references a missing goal.")
            if not isinstance(revision.get("before"), dict) or not isinstance(
                revision.get("after"), dict
            ):
                raise AccountabilityError("A goal revision needs before and after snapshots.")
            if not isinstance(revision.get("changes"), dict) or not revision["changes"]:
                raise AccountabilityError("A goal revision needs at least one recorded change.")
            parse_datetime(revision.get("revised_at"))

        commitment_ids: set[str] = set()
        for item in data["commitments"]:
            item_id = item.get("id")
            if not item_id or item_id in commitment_ids:
                raise AccountabilityError("Every commitment needs a unique id.")
            commitment_ids.add(item_id)
            if not str(item.get("title", "")).strip():
                raise AccountabilityError(f"Commitment {item_id} needs a title.")
            if item.get("status") not in COMMITMENT_STATUSES:
                raise AccountabilityError(f"Commitment {item_id} has an invalid status.")
            if item.get("priority") not in PRIORITIES:
                raise AccountabilityError(f"Commitment {item_id} has an invalid priority.")
            if item.get("goal_id") and item["goal_id"] not in goals:
                raise AccountabilityError(f"Commitment {item_id} references a missing goal.")
            parse_datetime(item.get("due_at"))
            parse_datetime(item.get("check_in_at"))
            parse_datetime(item.get("archived_at"))
            if not isinstance(item.get("win_conditions"), list):
                raise AccountabilityError(
                    f"Commitment {item_id} win conditions must be a list."
                )
            condition_ids: set[str] = set()
            for condition in item["win_conditions"]:
                condition_id = condition.get("id")
                if not condition_id or condition_id in condition_ids:
                    raise AccountabilityError(
                        f"Commitment {item_id} has an invalid win-condition id."
                    )
                condition_ids.add(condition_id)
                if not str(condition.get("text", "")).strip():
                    raise AccountabilityError("A win condition needs descriptive text.")
                if not isinstance(condition.get("completed"), bool):
                    raise AccountabilityError("Win-condition completion must be true or false.")
                if condition["completed"] and not condition.get("completed_at"):
                    raise AccountabilityError(
                        "A completed win condition needs a completion timestamp."
                    )
                parse_datetime(condition.get("completed_at"))

            if not isinstance(item.get("dependencies"), list):
                raise AccountabilityError(
                    f"Commitment {item_id} dependencies must be a list."
                )

        dependency_graph: dict[str, list[str]] = {}
        for item in data["commitments"]:
            item_id = item["id"]
            dependency_ids: set[str] = set()
            dependency_graph[item_id] = []
            for dependency in item["dependencies"]:
                dependency_id = dependency.get("commitment_id")
                if dependency_id not in commitment_ids:
                    raise AccountabilityError(
                        f"Commitment {item_id} references a missing dependency."
                    )
                if dependency_id == item_id:
                    raise AccountabilityError(
                        f"Commitment {item_id} cannot depend on itself."
                    )
                if dependency_id in dependency_ids:
                    raise AccountabilityError(
                        f"Commitment {item_id} lists a dependency more than once."
                    )
                if dependency.get("kind") not in DEPENDENCY_KINDS:
                    raise AccountabilityError(
                        f"Commitment {item_id} has an invalid dependency kind."
                    )
                dependency_ids.add(dependency_id)
                dependency_graph[item_id].append(dependency_id)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(commitment_id: str) -> None:
            if commitment_id in visiting:
                raise AccountabilityError("Commitment dependencies contain a cycle.")
            if commitment_id in visited:
                return
            visiting.add(commitment_id)
            for dependency_id in dependency_graph[commitment_id]:
                visit(dependency_id)
            visiting.remove(commitment_id)
            visited.add(commitment_id)

        for commitment_id in dependency_graph:
            visit(commitment_id)

        for check_in in data["check_ins"]:
            if check_in.get("commitment_id") not in commitment_ids:
                raise AccountabilityError("A check-in references a missing commitment.")
            if check_in.get("state") not in CHECK_IN_STATES:
                raise AccountabilityError("A check-in has an invalid state.")

    def save(self) -> None:
        self.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)
        if self.on_save is not None:
            self.on_save()

    def goals(self) -> list[dict[str, Any]]:
        return sorted(self.data["goals"], key=lambda item: item["title"].lower())

    def goal(self, goal_id: str | None) -> dict[str, Any] | None:
        if not goal_id:
            return None
        return next((g for g in self.data["goals"] if g["id"] == goal_id), None)

    def commitment(self, commitment_id: str) -> dict[str, Any]:
        item = next(
            (c for c in self.data["commitments"] if c["id"] == commitment_id),
            None,
        )
        if item is None:
            raise AccountabilityError(f"Unknown commitment '{commitment_id}'.")
        return item

    def add_goal(
        self, title: str, why: str = "", target_date: str | None = None
    ) -> dict[str, Any]:
        if not title.strip():
            raise AccountabilityError("A goal needs a title.")
        parsed_target = parse_date(target_date)
        goal = {
            "id": new_id("goal"),
            "title": title.strip(),
            "why": why.strip(),
            "target_date": parsed_target.isoformat() if parsed_target else None,
            "status": "active",
            "created_at": iso_now(),
        }
        self.data["goals"].append(goal)
        self._activity("goal_created", goal["id"], f"Created goal: {goal['title']}")
        self.save()
        return deepcopy(goal)

    def revise_goal(
        self,
        goal_id: str,
        title: str,
        why: str,
        target_date: str | None,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        goal = self.goal(goal_id)
        if goal is None:
            raise AccountabilityError(f"Unknown goal '{goal_id}'.")
        if not title.strip():
            raise AccountabilityError("A goal needs a title.")
        if status not in GOAL_STATUSES:
            raise AccountabilityError(f"Unknown goal status '{status}'.")
        if not reason.strip():
            raise AccountabilityError("Explain why the goal is being revised.")

        parsed_target = parse_date(target_date)
        before = {
            "title": goal["title"],
            "why": goal.get("why", ""),
            "target_date": goal.get("target_date"),
            "status": goal.get("status", "active"),
        }
        after = {
            "title": title.strip(),
            "why": why.strip(),
            "target_date": parsed_target.isoformat() if parsed_target else None,
            "status": status,
        }
        changes = {
            field: {"from": before[field], "to": after[field]}
            for field in before
            if before[field] != after[field]
        }
        if not changes:
            raise AccountabilityError("Nothing changed in this goal revision.")

        goal.update(after)
        revision = {
            "id": new_id("goal_revision"),
            "goal_id": goal_id,
            "revised_at": iso_now(),
            "reason": reason.strip(),
            "changes": changes,
            "before": before,
            "after": after,
        }
        self.data["goal_revisions"].append(revision)
        changed_fields = ", ".join(changes)
        self._activity(
            "goal_revised",
            goal_id,
            f"Revised goal ({changed_fields}): {goal['title']}",
        )
        self.save()
        return deepcopy(revision)

    def goal_revisions_for(self, goal_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(revision)
            for revision in reversed(self.data["goal_revisions"])
            if revision["goal_id"] == goal_id
        ]

    def add_win_condition(self, commitment_id: str, text: str) -> dict[str, Any]:
        commitment = self.commitment(commitment_id)
        cleaned = text.strip()
        if not cleaned:
            raise AccountabilityError("A win condition needs descriptive text.")
        if any(
            condition["text"].strip().casefold() == cleaned.casefold()
            for condition in commitment["win_conditions"]
        ):
            raise AccountabilityError("That win condition already exists.")
        condition = {
            "id": new_id("condition"),
            "text": cleaned,
            "completed": False,
            "created_at": iso_now(),
            "completed_at": None,
        }
        commitment["win_conditions"].append(condition)
        self._activity(
            "win_condition_created",
            commitment_id,
            f"Added win condition to {commitment['title']}: {cleaned}",
        )
        self.save()
        return deepcopy(condition)

    def set_win_condition(
        self, commitment_id: str, condition_id: str, completed: bool
    ) -> dict[str, Any]:
        commitment = self.commitment(commitment_id)
        condition = next(
            (
                item
                for item in commitment["win_conditions"]
                if item["id"] == condition_id
            ),
            None,
        )
        if condition is None:
            raise AccountabilityError(f"Unknown win condition '{condition_id}'.")
        if condition["completed"] == completed:
            return deepcopy(condition)
        condition["completed"] = completed
        condition["completed_at"] = iso_now() if completed else None
        action = "completed" if completed else "reopened"
        self._activity(
            f"win_condition_{action}",
            commitment_id,
            f"Win condition {action} for {commitment['title']}: {condition['text']}",
        )
        self.save()
        return deepcopy(condition)

    def commitment_progress(self, commitment_id: str) -> dict[str, Any]:
        commitment = self.commitment(commitment_id)
        total = len(commitment["win_conditions"])
        completed = sum(
            1
            for condition in commitment["win_conditions"]
            if condition["completed"]
        )
        return {
            "completed": completed,
            "total": total,
            "ratio": completed / total if total else 0.0,
            "all_met": total > 0 and completed == total,
        }

    def remove_win_condition(
        self, commitment_id: str, condition_id: str
    ) -> dict[str, Any]:
        commitment = self.commitment(commitment_id)
        index = next(
            (
                position
                for position, condition in enumerate(commitment["win_conditions"])
                if condition["id"] == condition_id
            ),
            None,
        )
        if index is None:
            raise AccountabilityError(f"Unknown win condition '{condition_id}'.")
        removed = commitment["win_conditions"].pop(index)
        self._activity(
            "win_condition_removed",
            commitment_id,
            f"Removed win condition from {commitment['title']}: {removed['text']}",
        )
        self.save()
        return deepcopy(removed)

    def add_dependency(
        self, commitment_id: str, dependency_id: str, kind: str = "required"
    ) -> dict[str, Any]:
        commitment = self.commitment(commitment_id)
        dependency = self.commitment(dependency_id)
        if commitment_id == dependency_id:
            raise AccountabilityError("A commitment cannot depend on itself.")
        if kind not in DEPENDENCY_KINDS:
            raise AccountabilityError(f"Unknown dependency kind '{kind}'.")
        if any(
            item["commitment_id"] == dependency_id
            for item in commitment["dependencies"]
        ):
            raise AccountabilityError("That dependency is already linked.")

        relationship = {
            "commitment_id": dependency_id,
            "kind": kind,
            "created_at": iso_now(),
        }
        commitment["dependencies"].append(relationship)
        try:
            self.validate()
        except AccountabilityError:
            commitment["dependencies"].pop()
            raise
        self._activity(
            "dependency_linked",
            commitment_id,
            f"Linked {kind} dependency for {commitment['title']}: {dependency['title']}",
        )
        self.save()
        return deepcopy(relationship)

    def remove_dependency(
        self, commitment_id: str, dependency_id: str
    ) -> dict[str, Any]:
        commitment = self.commitment(commitment_id)
        index = next(
            (
                position
                for position, item in enumerate(commitment["dependencies"])
                if item["commitment_id"] == dependency_id
            ),
            None,
        )
        if index is None:
            raise AccountabilityError("That dependency is not linked.")
        removed = commitment["dependencies"].pop(index)
        dependency = self.commitment(dependency_id)
        self._activity(
            "dependency_unlinked",
            commitment_id,
            f"Unlinked dependency for {commitment['title']}: {dependency['title']}",
        )
        self.save()
        return deepcopy(removed)

    def dependencies_for(self, commitment_id: str) -> list[dict[str, Any]]:
        commitment = self.commitment(commitment_id)
        result = []
        for relationship in commitment["dependencies"]:
            dependency = deepcopy(self.commitment(relationship["commitment_id"]))
            dependency["dependency_kind"] = relationship["kind"]
            dependency["display_status"] = classify_commitment(dependency)
            result.append(dependency)
        return result

    def dependents_for(self, commitment_id: str) -> list[dict[str, Any]]:
        self.commitment(commitment_id)
        result = []
        for candidate in self.data["commitments"]:
            relationship = next(
                (
                    item
                    for item in candidate["dependencies"]
                    if item["commitment_id"] == commitment_id
                ),
                None,
            )
            if relationship:
                dependent = deepcopy(candidate)
                dependent["dependency_kind"] = relationship["kind"]
                dependent["display_status"] = classify_commitment(dependent)
                result.append(dependent)
        return result

    def delete_commitment(self, commitment_id: str) -> dict[str, Any]:
        """Permanently remove a commitment and all live references to it."""
        commitment = self.commitment(commitment_id)
        self.data["commitments"] = [
            item
            for item in self.data["commitments"]
            if item["id"] != commitment_id
        ]
        self.data["check_ins"] = [
            item
            for item in self.data["check_ins"]
            if item["commitment_id"] != commitment_id
        ]
        for candidate in self.data["commitments"]:
            candidate["dependencies"] = [
                relationship
                for relationship in candidate["dependencies"]
                if relationship["commitment_id"] != commitment_id
            ]
        self._activity(
            "commitment_deleted",
            commitment_id,
            f"Deleted commitment: {commitment['title']}",
        )
        self.save()
        return deepcopy(commitment)

    def archive_commitment(self, commitment_id: str) -> dict[str, Any]:
        """Hide a closed commitment from normal views without deleting it."""
        item = self.commitment(commitment_id)
        if item["status"] not in TERMINAL_STATUSES:
            raise AccountabilityError(
                "Complete or triage a commitment before archiving it."
            )
        if item.get("archived_at"):
            return deepcopy(item)
        item["archived_at"] = iso_now()
        self._activity(
            "commitment_archived",
            commitment_id,
            f"Archived commitment: {item['title']}",
        )
        self.save()
        return deepcopy(item)

    def restore_commitment(self, commitment_id: str) -> dict[str, Any]:
        """Return an archived commitment to the normal closed-work view."""
        item = self.commitment(commitment_id)
        if not item.get("archived_at"):
            return deepcopy(item)
        item["archived_at"] = None
        self._activity(
            "commitment_restored",
            commitment_id,
            f"Restored archived commitment: {item['title']}",
        )
        self.save()
        return deepcopy(item)

    def add_commitment(
        self,
        title: str,
        due_at: str,
        goal_id: str | None = None,
        win_conditions: list[str] | None = None,
        why: str = "",
        priority: str = "medium",
        check_in_at: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        if not title.strip():
            raise AccountabilityError("A commitment needs a title.")
        if priority not in PRIORITIES:
            raise AccountabilityError(f"Unknown priority '{priority}'.")
        if goal_id and not self.goal(goal_id):
            raise AccountabilityError(f"Unknown goal '{goal_id}'.")
        normalized_due = normalize_datetime(due_at)
        if not normalized_due:
            raise AccountabilityError("A commitment needs a due date and time.")

        condition_items = []
        seen_conditions: set[str] = set()
        for condition_text in win_conditions or []:
            cleaned = condition_text.strip()
            if not cleaned:
                continue
            normalized = cleaned.casefold()
            if normalized in seen_conditions:
                raise AccountabilityError(f"Duplicate win condition: {cleaned}")
            seen_conditions.add(normalized)
            condition_items.append(
                {
                    "id": new_id("condition"),
                    "text": cleaned,
                    "completed": False,
                    "created_at": iso_now(),
                    "completed_at": None,
                }
            )

        item = {
            "id": new_id("commitment"),
            "goal_id": goal_id or None,
            "title": title.strip(),
            "why": why.strip(),
            "win_conditions": condition_items,
            "dependencies": [],
            "due_at": normalized_due,
            "check_in_at": normalize_datetime(check_in_at),
            "priority": priority,
            "status": "planned",
            "notes": notes.strip(),
            "created_at": iso_now(),
            "completed_at": None,
            "archived_at": None,
        }
        self.data["commitments"].append(item)
        self._activity(
            "commitment_created", item["id"], f"Committed to: {item['title']}"
        )
        self.save()
        return deepcopy(item)

    def set_commitment_status(
        self, commitment_id: str, status: str
    ) -> dict[str, Any]:
        if status not in COMMITMENT_STATUSES:
            raise AccountabilityError(f"Unknown status '{status}'.")
        item = self.commitment(commitment_id)
        previous = item["status"]
        item["status"] = status
        item["completed_at"] = iso_now() if status == "completed" else None
        if status in OPEN_STATUSES:
            item["archived_at"] = None
        self._activity(
            "status_changed",
            item["id"],
            f"Status changed from {previous} to {status}: {item['title']}",
        )
        self.save()
        return deepcopy(item)

    def set_commitment_goal(
        self, commitment_id: str, goal_id: str | None
    ) -> dict[str, Any]:
        item = self.commitment(commitment_id)
        new_goal = self.goal(goal_id) if goal_id else None
        if goal_id and new_goal is None:
            raise AccountabilityError(f"Unknown goal '{goal_id}'.")
        previous_goal = self.goal(item.get("goal_id"))
        previous_id = item.get("goal_id")
        if previous_id == goal_id:
            return deepcopy(item)

        item["goal_id"] = goal_id or None
        if previous_goal and new_goal:
            kind = "commitment_goal_changed"
            summary = (
                f"Changed goal for {item['title']}: "
                f"{previous_goal['title']} → {new_goal['title']}"
            )
        elif new_goal:
            kind = "commitment_goal_linked"
            summary = f"Linked {item['title']} to goal: {new_goal['title']}"
        else:
            kind = "commitment_goal_unlinked"
            previous_title = previous_goal["title"] if previous_goal else "unknown goal"
            summary = f"Unlinked {item['title']} from goal: {previous_title}"
        self._activity(kind, commitment_id, summary)
        self.save()
        return deepcopy(item)

    def record_check_in(
        self,
        commitment_id: str,
        state: str,
        note: str = "",
        next_action: str = "",
        next_check_in_at: str | None = None,
    ) -> dict[str, Any]:
        if state not in CHECK_IN_STATES:
            raise AccountabilityError(f"Unknown check-in state '{state}'.")
        item = self.commitment(commitment_id)
        normalized_next = normalize_datetime(next_check_in_at)
        check_in = {
            "id": new_id("checkin"),
            "commitment_id": commitment_id,
            "recorded_at": iso_now(),
            "state": state,
            "note": note.strip(),
            "next_action": next_action.strip(),
            "next_check_in_at": normalized_next,
        }
        self.data["check_ins"].append(check_in)
        item["check_in_at"] = normalized_next
        if state == "done":
            item["status"] = "completed"
            item["completed_at"] = iso_now()
        elif item["status"] == "planned":
            item["status"] = "in_progress"
        self._activity(
            "check_in_recorded",
            commitment_id,
            f"Check-in ({state.replace('_', ' ')}): {item['title']}",
        )
        self.save()
        return deepcopy(check_in)

    def check_ins_for(self, commitment_id: str) -> list[dict[str, Any]]:
        return [
            item
            for item in reversed(self.data["check_ins"])
            if item["commitment_id"] == commitment_id
        ]

    def commitments(
        self,
        include_closed: bool = False,
        include_archived: bool = False,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = now or now_local()
        items = [
            deepcopy(item)
            for item in self.data["commitments"]
            if (include_closed or item["status"] in OPEN_STATUSES)
            and (include_archived or not item.get("archived_at"))
        ]
        for item in items:
            item["display_status"] = classify_commitment(item, current)
        return sorted(
            items,
            key=lambda item: (
                item["status"] in TERMINAL_STATUSES,
                parse_datetime(item["due_at"]) or datetime.max.astimezone(),
                item["title"].lower(),
            ),
        )

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        current = now or now_local()
        active = self.commitments(now=current)
        counts = {
            "overdue": 0,
            "due_soon": 0,
            "check_in_due": 0,
            "active": len(active),
            "completed": sum(
                1
                for item in self.data["commitments"]
                if item["status"] == "completed" and not item.get("archived_at")
            ),
        }
        for item in active:
            state = item["display_status"]
            if state in counts:
                counts[state] += 1
        return {"as_of": current.isoformat(timespec="seconds"), "counts": counts, "items": active}

    def review_markdown(self, now: datetime | None = None) -> str:
        snapshot = self.snapshot(now)
        counts = snapshot["counts"]
        lines = [
            "# Accountability snapshot",
            "",
            f"As of {format_when(snapshot['as_of'])}",
            "",
            f"- Active: {counts['active']}",
            f"- Overdue: {counts['overdue']}",
            f"- Due soon: {counts['due_soon']}",
            f"- Check-ins due: {counts['check_in_due']}",
            f"- Completed: {counts['completed']}",
            "",
            "## Open commitments",
            "",
        ]
        if not snapshot["items"]:
            lines.append("No open commitments.")
        for item in snapshot["items"]:
            goal = self.goal(item.get("goal_id"))
            goal_text = f" · {goal['title']}" if goal else ""
            progress = self.commitment_progress(item["id"])
            dependencies = self.dependencies_for(item["id"])
            progress_text = [
                f"- Commitment progress: {progress['completed']}/{progress['total']} win conditions complete"
            ]
            for condition in item["win_conditions"]:
                marker = "x" if condition["completed"] else " "
                progress_text.append(f"  - [{marker}] {condition['text']}")
            dependency_text = ["- Dependencies: none"]
            if dependencies:
                dependency_text = ["- Dependencies:"]
                dependency_text.extend(
                    f"  - {dependency['dependency_kind']}: {dependency['title']} "
                    f"({dependency['display_status'].replace('_', ' ')})"
                    for dependency in dependencies
                )
            lines.extend(
                [
                    f"### {item['title']}",
                    "",
                    f"- State: {item['display_status'].replace('_', ' ')}{goal_text}",
                    f"- Due: {format_when(item['due_at'])}",
                    f"- Next check-in: {format_when(item.get('check_in_at'))}",
                    f"- Why: {item.get('why') or 'Not specified'}",
                    *progress_text,
                    *dependency_text,
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _activity(self, kind: str, subject_id: str, summary: str) -> None:
        self.data["activity"].append(
            {
                "id": new_id("activity"),
                "recorded_at": iso_now(),
                "kind": kind,
                "subject_id": subject_id,
                "summary": summary,
            }
        )
