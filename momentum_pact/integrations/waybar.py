from __future__ import annotations

import argparse
import json
import time
from html import escape
from pathlib import Path
from typing import Any, Iterator

from ..framework import AccountabilityError, AccountabilityStore, format_when
from ..paths import DEFAULT_DATA_PATH


ICONS = {
    "active": "󰄉",
    "check_in_due": "󰍴",
    "clear": "󰄬",
    "due_soon": "󰃰",
    "error": "󰅚",
    "overdue": "󰅚",
}
COUNTER_COLORS = {
    "active": "#66c2ff",
    "check_in_due": "#c99cff",
    "clear": "#5aafa2",
    "due_soon": "#ffd166",
    "overdue": "#ff4057",
}


def _counter(key: str, value: int | str) -> str:
    return (
        f'<span foreground="{COUNTER_COLORS[key]}">'
        f"{ICONS[key]} {value}</span>"
    )


def watch_waybar_payloads(
    data_path: Path, poll_interval: float = 0.5
) -> Iterator[dict[str, str]]:
    """Yield a new payload only when the accountability data file changes."""
    previous_signature: object = object()
    while True:
        try:
            stat = data_path.stat()
            signature: object = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except OSError as exc:
            signature = ("unavailable", str(exc))

        if signature != previous_signature:
            previous_signature = signature
            try:
                store = AccountabilityStore(data_path)
                yield waybar_payload(store.snapshot())
            except AccountabilityError as exc:
                yield waybar_error_payload(str(exc))
        time.sleep(poll_interval)


def waybar_payload(snapshot: dict[str, Any]) -> dict[str, str]:
    """Render an accountability snapshot as a Waybar custom-module payload."""
    counts = snapshot["counts"]
    status = _status_class(counts)
    in_progress = max(
        0,
        counts["active"]
        - counts["overdue"]
        - counts["due_soon"]
        - counts["check_in_due"],
    )
    status_parts = []
    for key in ("overdue", "due_soon", "check_in_due"):
        if counts[key]:
            status_parts.append(_counter(key, counts[key]))

    if in_progress:
        status_parts.append(_counter("active", in_progress))
    text = (
        "  ·  ".join(status_parts)
        if status_parts
        else _counter("clear", "clear")
    )

    return {
        "text": text,
        "tooltip": _tooltip(snapshot),
        "class": status,
        "alt": status,
    }


def waybar_error_payload(message: str) -> dict[str, str]:
    cleaned = escape(message.strip() or "Unknown Momentum Pact error")
    return {
        "text": f"{ICONS['error']} Momentum Pact",
        "tooltip": f"Momentum Pact could not read its data\n\n{cleaned}",
        "class": "error",
        "alt": "error",
    }


def _status_class(counts: dict[str, int]) -> str:
    if counts["overdue"]:
        return "overdue"
    if counts["check_in_due"]:
        return "check-in-due"
    if counts["due_soon"]:
        return "due-soon"
    if counts["active"]:
        return "active"
    return "clear"


def _tooltip(snapshot: dict[str, Any]) -> str:
    counts = snapshot["counts"]
    summary = (
        f"{counts['active']} open · {counts['overdue']} overdue · "
        f"{counts['due_soon']} due soon · {counts['check_in_due']} check-ins due"
    )
    lines = ["Momentum Pact", summary]
    items = snapshot.get("items", [])
    if not items:
        lines.extend(("", "No open commitments."))
        return "\n".join(lines)

    lines.extend(("", "Open commitments"))
    for item in items[:5]:
        state = str(item["display_status"]).replace("_", " ").upper()
        title = escape(str(item["title"]))
        lines.append(f"{state} · {title}")
        lines.append(f"  {escape(format_when(item.get('due_at')))}")
    if len(items) > 5:
        lines.append(f"…and {len(items) - 5} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Emit one Waybar payload or watch the data file for changes."""
    parser = argparse.ArgumentParser(description="Momentum Pact Waybar integration")
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA_PATH, help="JSON data file"
    )
    parser.add_argument(
        "--watch", action="store_true", help="Stream updates as the data file changes"
    )
    args = parser.parse_args(argv)

    if args.watch:
        try:
            for payload in watch_waybar_payloads(args.data):
                print(json.dumps(payload, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            pass
        return 0

    try:
        payload = waybar_payload(AccountabilityStore(args.data).snapshot())
    except AccountabilityError as exc:
        payload = waybar_error_payload(str(exc))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
