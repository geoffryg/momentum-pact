from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .framework import AccountabilityStore, now_local


def build_demo_data(path: Path, now: datetime | None = None) -> AccountabilityStore:
    """Create a neutral product-tour dataset covering every dashboard feature."""
    current = now or now_local()
    store = AccountabilityStore(path)

    routines = store.add_goal(
        "Keep weekly routines manageable",
        why="Make ordinary weeks require less last-minute effort.",
        target_date=(current + timedelta(days=30)).date().isoformat(),
    )
    admin = store.add_goal(
        "Finish routine administration",
        why="Keep small obligations from becoming avoidable emergencies.",
        target_date=(current + timedelta(days=21)).date().isoformat(),
    )
    home = store.add_goal(
        "Maintain a comfortable shared space",
        target_date=(current + timedelta(days=14)).date().isoformat(),
    )
    optional = store.add_goal(
        "Explore optional improvements",
        target_date=(current + timedelta(days=60)).date().isoformat(),
    )
    store.revise_goal(
        admin["id"],
        title="Stay on top of everyday administration",
        why="Handle routine obligations early enough to preserve flexibility.",
        target_date=(current + timedelta(days=30)).date().isoformat(),
        status="active",
        reason="Broadened the goal beyond the first administrative task.",
    )
    store.revise_goal(
        home["id"],
        title=home["title"],
        why="",
        target_date=home["target_date"],
        status="achieved",
        reason="The current home reset is complete.",
    )
    store.revise_goal(
        optional["id"],
        title=optional["title"],
        why="",
        target_date=optional["target_date"],
        status="paused",
        reason="Paused to protect time for active commitments.",
    )

    meals = store.add_commitment(
        "Choose meals for the week",
        (current + timedelta(hours=6)).isoformat(timespec="minutes"),
        goal_id=routines["id"],
        win_conditions=["Choose three simple meals", "Write a shopping list"],
        priority="medium",
        notes="Prefer familiar meals with overlapping ingredients.",
    )
    store.set_win_condition(
        meals["id"], meals["win_conditions"][0]["id"], True
    )

    weather = store.add_commitment(
        "Check the weekend weather",
        (current + timedelta(days=4)).isoformat(timespec="minutes"),
        win_conditions=["Review the forecast for Saturday and Sunday"],
        priority="low",
    )
    groceries = store.add_commitment(
        "Buy groceries",
        (current + timedelta(days=2)).isoformat(timespec="minutes"),
        goal_id=routines["id"],
        win_conditions=[
            "Bring the reusable bags",
            "Pick up everything on the shopping list",
        ],
        notes="Use the list prepared during meal planning.",
    )
    store.set_win_condition(
        groceries["id"], groceries["win_conditions"][0]["id"], True
    )
    store.record_check_in(
        groceries["id"],
        state="on_track",
        note="The list and transportation are ready.",
        next_action="Go to the store after work.",
        next_check_in_at=(current + timedelta(days=1, hours=2)).isoformat(
            timespec="minutes"
        ),
    )
    store.add_dependency(groceries["id"], meals["id"], "required")
    store.add_dependency(groceries["id"], weather["id"], "helpful")

    library = store.add_commitment(
        "Renew library books",
        (current - timedelta(hours=2)).isoformat(timespec="minutes"),
        goal_id=admin["id"],
        win_conditions=["Open the library account", "Renew eligible items"],
        priority="high",
        notes="One item may need to be returned in person.",
    )
    store.set_win_condition(
        library["id"], library["win_conditions"][0]["id"], True
    )

    appointment = store.add_commitment(
        "Schedule an annual appointment",
        (current + timedelta(days=3)).isoformat(timespec="minutes"),
        goal_id=admin["id"],
        win_conditions=["Find the office number", "Book an available time"],
    )
    store.record_check_in(
        appointment["id"],
        state="blocked",
        note="The office was closed when I called.",
        next_action="Call during business hours.",
        next_check_in_at=(current + timedelta(hours=2)).isoformat(timespec="minutes"),
    )
    store.record_check_in(
        appointment["id"],
        state="at_risk",
        note="The callback still needs to happen today.",
        next_action="Call before lunch.",
        next_check_in_at=(current - timedelta(hours=1)).isoformat(timespec="minutes"),
    )

    recycling = store.add_commitment(
        "Take out the recycling",
        (current - timedelta(days=1)).isoformat(timespec="minutes"),
        goal_id=home["id"],
        win_conditions=["Sort the recycling", "Move it to the collection area"],
        priority="low",
    )
    for condition in recycling["win_conditions"]:
        store.set_win_condition(recycling["id"], condition["id"], True)
    store.record_check_in(
        recycling["id"],
        state="done",
        note="Everything is at the collection area.",
        next_action="",
    )

    weekend = store.add_commitment(
        "Plan a weekend activity",
        (current + timedelta(days=5)).isoformat(timespec="minutes"),
        win_conditions=["Choose one activity", "Confirm the time and location"],
        priority="low",
    )
    store.add_dependency(weekend["id"], weather["id"], "helpful")

    triaged = store.add_commitment(
        "Organize a spare drawer",
        (current + timedelta(days=7)).isoformat(timespec="minutes"),
        goal_id=optional["id"],
        win_conditions=["Empty the drawer", "Return only useful items"],
        priority="low",
        notes="A deliberately deprioritized example.",
    )
    store.set_commitment_status(triaged["id"], "triaged")

    archived = store.add_commitment(
        "Return a borrowed item",
        (current - timedelta(days=2)).isoformat(timespec="minutes"),
        goal_id=home["id"],
        win_conditions=["Hand the item back to its owner"],
        priority="low",
        notes="Visible in the Archived view as a restoration example.",
    )
    store.set_win_condition(
        archived["id"], archived["win_conditions"][0]["id"], True
    )
    store.set_commitment_status(archived["id"], "completed")
    store.archive_commitment(archived["id"])

    store.add_commitment(
        "Read the community bulletin",
        (current + timedelta(days=6)).isoformat(timespec="minutes"),
        win_conditions=["Review this week's announcements"],
        priority="medium",
        notes="This example intentionally has no linked goal.",
    )

    return store


def launch_demo() -> None:
    """Run an isolated demo whose temporary data lives as long as its window."""
    from .app import main as app_main

    with tempfile.TemporaryDirectory(prefix="momentum-pact-demo.") as directory:
        data_path = Path(directory) / "accountability.json"
        build_demo_data(data_path)
        app_main(
            [
                "--data",
                str(data_path),
                "--title",
                "Momentum Pact Demo · Example Data",
            ]
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Create neutral Momentum Pact demo data."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--launch", action="store_true")
    args = parser.parse_args(argv)
    if args.launch:
        launch_demo()
    else:
        build_demo_data(args.output)


if __name__ == "__main__":
    main()
