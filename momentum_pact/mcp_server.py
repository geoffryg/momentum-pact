"""Read-only local MCP access to Momentum Pact commitments."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from .framework import AccountabilityStore, classify_commitment
from .paths import DEFAULT_DATA_PATH


def list_commitments(data_path: str | Path) -> list[dict[str, Any]]:
    """Read a compact index of every commitment, including archived ones."""
    store = AccountabilityStore(data_path)
    return [
        {
            "id": commitment["id"],
            "title": commitment["title"],
            "status": commitment["status"],
            "due": commitment["due_at"],
            "priority": commitment["priority"],
            "goal_id": commitment.get("goal_id"),
        }
        for commitment in store.commitments(
            include_closed=True,
            include_archived=True,
        )
    ]


def get_commitment(data_path: str | Path, commitment_id: str) -> dict[str, Any]:
    """Read one commitment by id without exposing the store's mutable record."""
    store = AccountabilityStore(data_path)
    commitment = deepcopy(store.commitment(commitment_id))
    commitment["display_status"] = classify_commitment(commitment)
    return commitment


def register_tools(server: Any, data_path: str | Path) -> Any:
    """Register the two read-only tools on an MCP server instance."""
    resolved_path = Path(data_path)

    @server.tool(name="listCommitments")
    async def list_commitments_tool() -> list[dict[str, Any]]:
        """List compact summaries of all commitments. This tool is read-only."""
        return list_commitments(resolved_path)

    @server.tool(name="getCommitment")
    async def get_commitment_tool(id: str) -> dict[str, Any]:
        """Get one Momentum Pact commitment by id. This tool is read-only."""
        return get_commitment(resolved_path, id)

    return server


def create_server(data_path: str | Path = DEFAULT_DATA_PATH) -> Any:
    """Create the local stdio MCP server."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "The MCP dependency is not installed. Install Momentum Pact with "
            "`python3 -m pip install -e '.[mcp]'`."
        ) from exc

    server = MCPServer(
        "Momentum Pact",
        instructions=(
            "Read-only access to local Momentum Pact commitments. "
            "This server exposes no mutation tools."
        ),
    )
    return register_tools(server, data_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only Momentum Pact MCP server over stdio."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="Accountability JSON file to read",
    )
    args = parser.parse_args(argv)
    create_server(args.data).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
