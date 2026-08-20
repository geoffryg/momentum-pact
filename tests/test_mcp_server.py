import tempfile
import unittest
from pathlib import Path

from momentum_pact.framework import AccountabilityError, AccountabilityStore
from momentum_pact.mcp_server import (
    create_server,
    get_commitment,
    list_commitments,
    register_tools,
)


class FakeMCPServer:
    def __init__(self):
        self.tools = {}

    def tool(self, *, name):
        def decorate(function):
            self.tools[name] = function
            return function

        return decorate


class MCPReadToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name) / "accountability.json"
        self.store = AccountabilityStore(self.data_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_commitments_returns_open_closed_and_archived_records(self):
        open_item = self.store.add_commitment("Open item", "2030-01-01 12:00")
        closed_item = self.store.add_commitment("Closed item", "2030-01-02 12:00")
        self.store.set_commitment_status(closed_item["id"], "completed")
        self.store.archive_commitment(closed_item["id"])

        result = list_commitments(self.data_path)

        self.assertEqual(
            {item["id"] for item in result}, {open_item["id"], closed_item["id"]}
        )
        self.assertTrue(all("display_status" in item for item in result))

    def test_get_commitment_returns_a_copy_with_display_status(self):
        item = self.store.add_commitment("Read one item", "2030-01-01 12:00")

        result = get_commitment(self.data_path, item["id"])
        result["title"] = "Changed outside the store"

        self.assertEqual(result["display_status"], "planned")
        self.assertEqual(
            AccountabilityStore(self.data_path).commitment(item["id"])["title"],
            "Read one item",
        )

    def test_get_commitment_rejects_an_unknown_id(self):
        with self.assertRaisesRegex(AccountabilityError, "Unknown commitment"):
            get_commitment(self.data_path, "commitment_missing")

    def test_empty_reads_do_not_create_a_data_file(self):
        self.assertEqual(list_commitments(self.data_path), [])
        self.assertFalse(self.data_path.exists())

    def test_reads_do_not_modify_an_existing_data_file(self):
        item = self.store.add_commitment("Leave unchanged", "2030-01-01 12:00")
        before = self.data_path.read_bytes()

        list_commitments(self.data_path)
        get_commitment(self.data_path, item["id"])

        self.assertEqual(self.data_path.read_bytes(), before)

    def test_registers_only_the_requested_read_tools(self):
        server = register_tools(FakeMCPServer(), self.data_path)

        self.assertEqual(set(server.tools), {"listCommitments", "getCommitment"})


try:
    from mcp import Client
except ImportError:  # pragma: no cover - exercised without the optional extra
    Client = None


@unittest.skipIf(Client is None, "MCP optional dependency is not installed")
class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_lists_and_calls_read_tools_in_process(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "accountability.json"
            item = AccountabilityStore(data_path).add_commitment(
                "Protocol item", "2030-01-01 12:00"
            )
            server = create_server(data_path)

            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {tool.name for tool in tools.tools},
                    {"listCommitments", "getCommitment"},
                )
                listed = await client.call_tool("listCommitments", {})
                fetched = await client.call_tool(
                    "getCommitment", {"id": item["id"]}
                )

            self.assertFalse(listed.is_error)
            self.assertEqual(
                listed.structured_content["result"][0]["id"], item["id"]
            )
            self.assertFalse(fetched.is_error)
            self.assertEqual(fetched.structured_content["id"], item["id"])


if __name__ == "__main__":
    unittest.main()
