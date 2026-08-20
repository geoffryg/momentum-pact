# Local MCP server

Momentum Pact includes an optional read-only MCP server for local clients. It
uses the same `AccountabilityStore` as the dashboard and reads the JSON data file
directly; it does not invoke the CLI or any shell command.

The server exposes exactly two tools:

- `listCommitments()` returns all commitments, including completed, triaged, and
  archived records.
- `getCommitment(id)` returns the complete record for one commitment id.

There are no write, email, network, reminder, or autonomous-action tools.

## Install

From the repository root, create an environment and install the MCP extra:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp]'
```

## Launch

Run the stdio server with the normal per-user data location:

```sh
.venv/bin/python -m momentum_pact.mcp_server
```

To read a specific data file, including the checkout-local file used by the
Linux launch helpers:

```sh
.venv/bin/python -m momentum_pact.mcp_server \
  --data /absolute/path/to/accountability.json
```

An MCP client configuration can launch it directly:

```json
{
  "mcpServers": {
    "momentum-pact": {
      "command": "/absolute/path/to/momentum-pact/.venv/bin/python",
      "args": [
        "-m",
        "momentum_pact.mcp_server",
        "--data",
        "/absolute/path/to/accountability.json"
      ]
    }
  }
}
```

Use absolute paths because MCP hosts do not necessarily start servers from the
repository directory. The process communicates over standard input and output;
it does not open a network port.
