from __future__ import annotations

import argparse
import json
from pathlib import Path

from .framework import AccountabilityError, AccountabilityStore, format_when
from .paths import DEFAULT_DATA_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and update Momentum Pact accountability data."
    )
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA_PATH, help="JSON data file"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list", help="List commitments")
    list_scope = list_parser.add_mutually_exclusive_group()
    list_scope.add_argument(
        "--all", action="store_true", help="Include completed and triaged"
    )
    list_scope.add_argument(
        "--archived", action="store_true", help="Show only archived commitments"
    )
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    commands.add_parser("review", help="Print a review-ready Markdown snapshot")
    commands.add_parser("validate", help="Validate the data file")
    goal_parser = commands.add_parser("goal-add", help="Create a goal")
    goal_parser.add_argument("title")
    goal_parser.add_argument("--why", default="")
    goal_parser.add_argument("--target-date")

    revise_goal_parser = commands.add_parser(
        "goal-revise", help="Revise a goal and preserve its history"
    )
    revise_goal_parser.add_argument("goal_id")
    revise_goal_parser.add_argument("--title")
    revise_goal_parser.add_argument("--why")
    revise_goal_parser.add_argument("--target-date")
    revise_goal_parser.add_argument("--clear-target-date", action="store_true")
    revise_goal_parser.add_argument(
        "--status", choices=("active", "paused", "achieved")
    )
    revise_goal_parser.add_argument("--reason", required=True)

    goal_history_parser = commands.add_parser(
        "goal-history", help="Show the revision history for a goal"
    )
    goal_history_parser.add_argument("goal_id")

    condition_add_parser = commands.add_parser(
        "commitment-condition-add",
        help="Add an observable win condition to a commitment",
    )
    condition_add_parser.add_argument("commitment_id")
    condition_add_parser.add_argument("text")

    condition_list_parser = commands.add_parser(
        "commitment-conditions", help="List commitment win conditions and progress"
    )
    condition_list_parser.add_argument("commitment_id")

    condition_set_parser = commands.add_parser(
        "commitment-condition-set",
        help="Complete or reopen a commitment win condition",
    )
    condition_set_parser.add_argument("commitment_id")
    condition_set_parser.add_argument("condition_id")
    condition_state = condition_set_parser.add_mutually_exclusive_group(required=True)
    condition_state.add_argument("--complete", action="store_true")
    condition_state.add_argument("--reopen", action="store_true")

    condition_remove_parser = commands.add_parser(
        "commitment-condition-remove", help="Remove a commitment win condition"
    )
    condition_remove_parser.add_argument("commitment_id")
    condition_remove_parser.add_argument("condition_id")

    dependency_add_parser = commands.add_parser(
        "dependency-add", help="Link a prerequisite commitment"
    )
    dependency_add_parser.add_argument("commitment_id")
    dependency_add_parser.add_argument("dependency_id")
    dependency_add_parser.add_argument(
        "--kind", choices=("required", "helpful"), default="required"
    )

    dependency_list_parser = commands.add_parser(
        "dependencies", help="List a commitment's dependencies"
    )
    dependency_list_parser.add_argument("commitment_id")

    dependency_remove_parser = commands.add_parser(
        "dependency-remove", help="Remove a dependency link"
    )
    dependency_remove_parser.add_argument("commitment_id")
    dependency_remove_parser.add_argument("dependency_id")

    goal_link_parser = commands.add_parser(
        "commitment-goal-set", help="Link, change, or unlink a commitment goal"
    )
    goal_link_parser.add_argument("commitment_id")
    goal_link = goal_link_parser.add_mutually_exclusive_group(required=True)
    goal_link.add_argument("--goal-id")
    goal_link.add_argument("--unlink", action="store_true")

    add_parser = commands.add_parser("add", help="Create a commitment")
    add_parser.add_argument("title")
    add_parser.add_argument("--due", required=True, help="YYYY-MM-DD HH:MM")
    add_parser.add_argument("--goal-id")
    add_parser.add_argument(
        "--win-condition",
        action="append",
        dest="win_conditions",
        required=True,
        help="Observable subtask; repeat for multiple conditions",
    )
    add_parser.add_argument("--why", default="")
    add_parser.add_argument("--priority", choices=("low", "medium", "high"), default="medium")
    add_parser.add_argument("--check-in")
    add_parser.add_argument("--notes", default="")

    delete_parser = commands.add_parser(
        "delete", help="Permanently delete a commitment and its live references"
    )
    delete_parser.add_argument("commitment_id")

    archive_parser = commands.add_parser(
        "archive", help="Archive a completed or triaged commitment"
    )
    archive_parser.add_argument("commitment_id")
    restore_parser = commands.add_parser(
        "restore", help="Restore a commitment from the archive"
    )
    restore_parser.add_argument("commitment_id")

    for name, help_text, status in (
        ("done", "Mark a commitment completed", "completed"),
        ("reopen", "Reopen a commitment", "in_progress"),
        ("triage", "Close a commitment as consciously triaged", "triaged"),
    ):
        status_parser = commands.add_parser(name, help=help_text)
        status_parser.add_argument("commitment_id")
        status_parser.set_defaults(target_status=status)

    check_parser = commands.add_parser("check-in", help="Record a progress check-in")
    check_parser.add_argument("commitment_id")
    check_parser.add_argument(
        "--state", choices=("on_track", "at_risk", "blocked", "done"), required=True
    )
    check_parser.add_argument("--note", default="")
    check_parser.add_argument("--next-action", default="")
    check_parser.add_argument("--next-check-in")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = AccountabilityStore(args.data)

        if args.command == "validate":
            print(f"Valid Momentum Pact data: {args.data}")
        elif args.command == "review":
            print(store.review_markdown(), end="")
        elif args.command == "list":
            items = store.commitments(
                include_closed=args.all or args.archived,
                include_archived=args.archived,
            )
            if args.archived:
                items = [item for item in items if item.get("archived_at")]
            if args.json:
                print(json.dumps(items, indent=2))
            elif not items:
                print("No commitments yet.")
            else:
                for item in items:
                    print(
                        f"{item['id']}  {item['display_status']:<12}  "
                        f"{format_when(item['due_at']):<30}  {item['title']}"
                    )
        elif args.command == "goal-add":
            goal = store.add_goal(args.title, args.why, args.target_date)
            print(f"Created {goal['id']}: {goal['title']}")
        elif args.command == "goal-revise":
            goal = store.goal(args.goal_id)
            if goal is None:
                raise AccountabilityError(f"Unknown goal '{args.goal_id}'.")
            target_date = (
                None
                if args.clear_target_date
                else args.target_date
                if args.target_date is not None
                else goal.get("target_date")
            )
            revision = store.revise_goal(
                goal_id=args.goal_id,
                title=args.title if args.title is not None else goal["title"],
                why=args.why if args.why is not None else goal.get("why", ""),
                target_date=target_date,
                status=args.status if args.status is not None else goal["status"],
                reason=args.reason,
            )
            print(f"Recorded {revision['id']} for {args.goal_id}.")
        elif args.command == "goal-history":
            goal = store.goal(args.goal_id)
            if goal is None:
                raise AccountabilityError(f"Unknown goal '{args.goal_id}'.")
            revisions = store.goal_revisions_for(args.goal_id)
            if not revisions:
                print(f"No revisions recorded for {goal['title']}.")
            for revision in revisions:
                print(f"{revision['revised_at']}  {revision['reason']}")
                for field, change in revision["changes"].items():
                    print(f"  {field}: {change['from']!r} -> {change['to']!r}")
        elif args.command == "commitment-condition-add":
            condition = store.add_win_condition(args.commitment_id, args.text)
            print(f"Created {condition['id']}: {condition['text']}")
        elif args.command == "commitment-conditions":
            commitment = store.commitment(args.commitment_id)
            progress = store.commitment_progress(args.commitment_id)
            print(
                f"{commitment['title']}: {progress['completed']}/{progress['total']} complete"
            )
            if not commitment["win_conditions"]:
                print("No win conditions yet.")
            for condition in commitment["win_conditions"]:
                marker = "x" if condition["completed"] else " "
                print(f"[{marker}] {condition['id']}  {condition['text']}")
        elif args.command == "commitment-condition-set":
            condition = store.set_win_condition(
                args.commitment_id, args.condition_id, completed=args.complete
            )
            state = "complete" if condition["completed"] else "open"
            print(f"{condition['id']} is now {state}.")
        elif args.command == "commitment-condition-remove":
            condition = store.remove_win_condition(
                args.commitment_id, args.condition_id
            )
            print(f"Removed {condition['id']}: {condition['text']}")
        elif args.command == "dependency-add":
            relationship = store.add_dependency(
                args.commitment_id, args.dependency_id, args.kind
            )
            dependency = store.commitment(relationship["commitment_id"])
            print(f"Linked {args.kind} dependency: {dependency['title']}")
        elif args.command == "dependencies":
            commitment = store.commitment(args.commitment_id)
            dependencies = store.dependencies_for(args.commitment_id)
            print(f"Dependencies for {commitment['title']}:")
            if not dependencies:
                print("No dependencies linked.")
            for dependency in dependencies:
                print(
                    f"{dependency['id']}  {dependency['dependency_kind']:<8}  "
                    f"{dependency['display_status']:<12}  {dependency['title']}"
                )
        elif args.command == "dependency-remove":
            dependency = store.commitment(args.dependency_id)
            store.remove_dependency(args.commitment_id, args.dependency_id)
            print(f"Removed dependency: {dependency['title']}")
        elif args.command == "commitment-goal-set":
            commitment = store.set_commitment_goal(
                args.commitment_id, None if args.unlink else args.goal_id
            )
            goal = store.goal(commitment.get("goal_id"))
            print(
                f"{commitment['id']} goal: "
                f"{goal['title'] if goal else 'No linked goal'}"
            )
        elif args.command == "add":
            item = store.add_commitment(
                title=args.title,
                due_at=args.due,
                goal_id=args.goal_id,
                win_conditions=args.win_conditions,
                why=args.why,
                priority=args.priority,
                check_in_at=args.check_in,
                notes=args.notes,
            )
            print(f"Created {item['id']}: {item['title']}")
        elif args.command == "delete":
            item = store.delete_commitment(args.commitment_id)
            print(f"Deleted {item['id']}: {item['title']}")
        elif args.command == "archive":
            item = store.archive_commitment(args.commitment_id)
            print(f"Archived {item['id']}: {item['title']}")
        elif args.command == "restore":
            item = store.restore_commitment(args.commitment_id)
            print(f"Restored {item['id']}: {item['title']}")
        elif args.command in {"done", "reopen", "triage"}:
            item = store.set_commitment_status(args.commitment_id, args.target_status)
            print(f"{item['id']} is now {item['status']}.")
        elif args.command == "check-in":
            check_in = store.record_check_in(
                commitment_id=args.commitment_id,
                state=args.state,
                note=args.note,
                next_action=args.next_action,
                next_check_in_at=args.next_check_in,
            )
            print(f"Recorded {check_in['id']} for {args.commitment_id}.")
        return 0
    except AccountabilityError as exc:
        print(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
