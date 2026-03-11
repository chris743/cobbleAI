# Porting CobbleAI Agent Tools to a Standalone MCP Server

This guide walks through extracting the 38 agent tools from the monolithic Flask app into a standalone [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server. After this migration, the Flask web app becomes a thin auth/chat layer and the tools run as an independent service.

---

## Why MCP

Right now everything is coupled: Flask imports `AgentToolkit` which imports pyodbc, O365, fpdf2, openpyxl, etc. The web frontend can't run without the entire tool stack installed.

An MCP server separates concerns:

```
BEFORE:
  React UI --> Flask API --> agent_claude.py --> AgentToolkit (all tools in-process)

AFTER:
  React UI --> Flask API --> Claude API (with MCP tool discovery)
                                  |
                            MCP Server (standalone process)
                              - SQL queries
                              - Excel/PDF exports
                              - Harvest Planner API
                              - O365 integration
                              - Learning, context, living docs
```

Benefits:
- **Frontend stands alone** — Flask only needs `anthropic`, `pymongo`, `flask`, `clerk`. No pyodbc, O365, fpdf2, etc.
- **Independent deployment** — tools server can run on a different machine (closer to SQL Server, for example)
- **Reusable** — any MCP-compatible client (Claude Desktop, other agents) can use your tools
- **Testable** — tools server can be tested independently of the web layer

---

## Architecture Overview

### MCP Server (new standalone process)

A Python process using the `mcp` SDK that exposes all 38 tools via stdio or SSE transport.

```
cobble-mcp-server/
  server.py              # MCP server entry point
  tools/                 # Copied from agent_tools/, adapted
    __init__.py
    config.py
    query_executor.py
    context_loader.py
    learning.py
    excel_exporter.py
    pdf_exporter.py
    harvest_planner.py
    living_documents.py
    o365_tools.py
    user_context.py
  requirements.txt       # pyodbc, O365, fpdf2, openpyxl, pymongo, mcp, etc.
  .env                   # DB creds, HP creds, O365 creds, Mongo URI
```

### Flask App (slimmed down)

The web app no longer imports `agent_tools`. Instead, `agent_claude.py` connects to the MCP server as a client. It only needs:
- `flask`, `flask-cors`, `anthropic`, `pymongo`, `clerk-backend-api`, `PyJWT`

---

## Step-by-Step Migration

### Step 1: Create the MCP Server

Install the MCP SDK (it's already in your venv as a transitive dep, but pin it):

```bash
pip install "mcp[cli]>=1.0"
```

Create `cobble-mcp-server/server.py`:

```python
"""CobbleAI MCP Tool Server."""

import json
from mcp.server.fastmcp import FastMCP

# Import your existing tool modules (copy agent_tools/ into tools/)
from tools import AgentToolkit
from tools.user_context import set_user_id

mcp = FastMCP("CobbleAI Tools")
toolkit = AgentToolkit()

# ── Register every tool ──────────────────────────────────────────────────────
# Loop over the existing TOOL_DEFINITIONS and register them dynamically.

_handlers = {}
_handlers.update(toolkit._build_handlers())  # we'll add this helper


def _register_tool(tool_def):
    """Register a single tool definition as an MCP tool."""
    name = tool_def["name"]
    description = tool_def["description"]
    schema = tool_def["parameters"]

    @mcp.tool(name=name, description=description)
    async def _handler(**kwargs):
        # If the caller passes _user_id, set it in context for O365 tools
        user_id = kwargs.pop("_user_id", None)
        if user_id:
            set_user_id(user_id)
        result = toolkit.handle_tool_call(name, kwargs)
        return json.dumps(result, default=str)

    # FastMCP needs the input schema — override it
    _handler.__mcp_tool_annotations__ = schema


# Simpler approach: register each tool explicitly for clarity and type safety.
# Here's the pattern for one tool, then we'll do it for all 38.

for tool_def in toolkit.get_tool_definitions():
    _register_tool(tool_def)


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
```

> **Note:** The dynamic registration above works but has a closure variable issue (all handlers would reference the last `name`). The production version below fixes this.

#### Production-ready dynamic registration

```python
"""CobbleAI MCP Tool Server — production version."""

import json
import logging
from mcp.server.fastmcp import FastMCP

from tools import AgentToolkit
from tools.user_context import set_user_id

logging.basicConfig(level=logging.INFO)
mcp = FastMCP("CobbleAI Tools")
toolkit = AgentToolkit()


def _make_handler(tool_name: str):
    """Create a closure that captures the tool name correctly."""
    async def handler(**kwargs) -> str:
        user_id = kwargs.pop("_user_id", None)
        if user_id:
            set_user_id(user_id)
        result = toolkit.handle_tool_call(tool_name, kwargs)
        return json.dumps(result, default=str)
    handler.__name__ = tool_name  # mcp uses __name__ for registration
    return handler


# Register all tools from existing definitions
for tool_def in toolkit.get_tool_definitions():
    name = tool_def["name"]
    mcp.tool(
        name=name,
        description=tool_def["description"],
    )(_make_handler(name))


if __name__ == "__main__":
    mcp.run()
```

### Step 2: Copy and Adapt the Tools Package

```bash
mkdir cobble-mcp-server
cp -r agent_tools/ cobble-mcp-server/tools/
cp customer_specs.py cobble-mcp-server/
cp living_docs.py cobble-mcp-server/
cp chat_store.py cobble-mcp-server/
cp o365_auth.py cobble-mcp-server/
cp -r data-catalog/ cobble-mcp-server/
cp -r agent-learning/ cobble-mcp-server/
```

Changes needed in the copied code:
- **`tools/__init__.py`**: No changes needed — `AgentToolkit` works as-is.
- **`tools/config.py`**: Add its own `load_dotenv()` pointing to the MCP server's `.env`.
- **`chat_store.py`** / **`living_docs.py`** / **`customer_specs.py`**: These import from each other — make sure paths resolve in the new location.
- **`tools/o365_tools.py`**: The `import o365_auth` path needs to be reachable.

### Step 3: Choose a Transport

#### Option A: stdio (simplest — same machine)

The Flask app spawns the MCP server as a subprocess. This is the simplest approach and what Claude Desktop uses.

```python
# In agent_claude.py, replace direct toolkit usage with MCP client
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="python",
    args=["cobble-mcp-server/server.py"],
    env={...}  # pass env vars
)

async def get_mcp_session():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
```

#### Option B: SSE over HTTP (separate machine / container)

Run the MCP server as an HTTP service:

```bash
# Start MCP server with SSE transport
cd cobble-mcp-server
python server.py --transport sse --port 9000
```

Connect from the Flask app:

```python
from mcp.client.sse import sse_client

async with sse_client("http://tools-server:9000/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("execute_sql", {"sql": "SELECT ..."})
```

#### Option C: Anthropic API with MCP (cleanest)

If you switch to the Anthropic API's built-in MCP connector (available in newer SDK versions), Claude handles the MCP communication directly:

```python
from anthropic import Anthropic

client = Anthropic()

# Claude connects to MCP server and discovers tools automatically
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=30000,
    system=SYSTEM_PROMPT,
    messages=messages,
    mcp_servers=[{
        "type": "url",
        "url": "http://tools-server:9000/sse",
    }]
)
```

This eliminates the manual tool-call loop in `agent_claude.py` entirely.

### Step 4: Update agent_claude.py

Replace the direct `AgentToolkit` usage with MCP client calls. Here's the full rewrite for **Option A (stdio)**:

```python
"""Agent orchestration via MCP tool server."""

import os
import json
import asyncio
from dotenv import load_dotenv
from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

client = Anthropic()
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TURNS = int(os.getenv("MAX_AGENT_TURNS", "10"))

with open("agent_system_prompt.md", "r") as f:
    SYSTEM_PROMPT = f.read()

MCP_SERVER = StdioServerParameters(
    command="python",
    args=[os.path.join(os.path.dirname(__file__), "cobble-mcp-server", "server.py")],
)


async def _run_streaming(messages, max_turns, log_fn, user_id=None):
    """Internal async streaming implementation."""
    async with stdio_client(MCP_SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Get tool definitions from MCP server
            mcp_tools = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema,
                }
                for t in mcp_tools.tools
            ]

            for turn in range(max_turns):
                with client.messages.stream(
                    model=MODEL,
                    max_tokens=30000,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if hasattr(event, "type"):
                            if (
                                event.type == "content_block_delta"
                                and hasattr(event.delta, "text")
                            ):
                                yield ("token", event.delta.text)
                    response = stream.get_final_message()

                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "end_turn":
                    return

                # Execute tool calls via MCP
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        log_fn(f"  [Tool Call] {block.name}")
                        yield ("tool", block.name)

                        # Inject user_id for O365 tools
                        params = dict(block.input)
                        if user_id:
                            params["_user_id"] = user_id

                        result = await session.call_tool(block.name, params)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result.content[0].text
                                if result.content
                                else "{}",
                            }
                        )

                messages.append({"role": "user", "content": tool_results})


def run_agent_turn_streaming(messages, max_turns=None, log_fn=None, user_id=None):
    """Sync generator wrapper for the async MCP implementation."""
    if log_fn is None:
        log_fn = print
    max_turns = max_turns or MAX_TURNS

    # Run async generator in a new event loop
    loop = asyncio.new_event_loop()
    try:
        agen = _run_streaming(messages, max_turns, log_fn, user_id)
        while True:
            try:
                event = loop.run_until_complete(agen.__anext__())
                yield event
            except StopAsyncIteration:
                break
    finally:
        loop.close()
```

### Step 5: Slim Down Flask Requirements

After migration, the Flask app's `requirements.txt` becomes:

```
anthropic>=0.84
flask>=3.1
flask-cors
pymongo>=4.0
PyJWT>=2.0
clerk-backend-api
python-dotenv
mcp>=1.0
```

All the heavy dependencies move to `cobble-mcp-server/requirements.txt`:

```
mcp>=1.0
pyodbc>=5.0
openpyxl>=3.1
fpdf2>=2.8
O365>=2.0
pymongo>=4.0
PyYAML>=6.0
httpx>=0.28
python-dotenv
RapidFuzz>=3.0
```

### Step 6: Handle File Downloads

The MCP server generates exports into `./exports/`. The Flask app needs to serve them. Two options:

**Option A: Shared filesystem** — Both processes mount the same `exports/` directory. Simplest if same machine.

**Option B: MCP resource** — Expose exports as MCP resources:

```python
# In server.py
@mcp.resource("export://{filename}")
async def get_export(filename: str) -> bytes:
    path = Path("./exports") / filename
    if not path.exists():
        raise FileNotFoundError(f"Export not found: {filename}")
    return path.read_bytes()
```

Then in Flask, fetch the file from MCP when the user requests a download. For simplicity, **Option A is recommended** — just point both processes at the same directory.

### Step 7: Handle User Context for O365

O365 tools need the Clerk user ID to fetch the right tokens. Since MCP tool calls are just JSON, pass `_user_id` as an extra parameter:

- MCP server side: each handler pops `_user_id` from kwargs and calls `set_user_id()`
- Flask/agent side: injects `_user_id` into tool call params before sending to MCP

This is already shown in the code above. The tool definitions don't include `_user_id` in their schema — it's injected at the orchestration layer.

---

## Migration Checklist

```
[ ] Create cobble-mcp-server/ directory
[ ] Copy agent_tools/ -> cobble-mcp-server/tools/
[ ] Copy supporting modules (chat_store, living_docs, customer_specs, o365_auth)
[ ] Copy data directories (data-catalog/, agent-learning/)
[ ] Create server.py with FastMCP registration
[ ] Create cobble-mcp-server/.env with DB, Mongo, HP, O365 credentials
[ ] Create cobble-mcp-server/requirements.txt
[ ] Test: python cobble-mcp-server/server.py (should start without errors)
[ ] Test: use mcp CLI to call a tool manually
      mcp call cobble-mcp-server/server.py execute_sql '{"sql":"SELECT 1 AS test"}'
[ ] Rewrite agent_claude.py to use MCP client
[ ] Remove agent_tools imports from web_app.py
[ ] Update Flask requirements.txt (remove pyodbc, O365, fpdf2, openpyxl)
[ ] Set up shared exports/ directory or MCP resource
[ ] Test full flow: React -> Flask -> Claude -> MCP -> SQL -> response
[ ] Update deployment scripts / Cloudflare tunnel config if needed
```

---

## Deployment Topology Options

### A. Same machine, stdio (simplest)

```
[Vite :5000] --> [Flask :8000] --spawns--> [MCP Server (stdio)]
```

Flask spawns the MCP server as a child process. No network config needed. The MCP server inherits env vars or reads its own `.env`. This is what you should start with.

### B. Same machine, SSE (more resilient)

```
[Vite :5000] --> [Flask :8000] --HTTP--> [MCP Server :9000]
```

MCP server runs as a separate long-lived process. Survives Flask restarts. Can be managed by systemd/supervisor.

```bash
# Start MCP server
cd cobble-mcp-server && python server.py --transport sse --port 9000

# Flask connects to it
MCP_SERVER_URL=http://localhost:9000/sse  # in Flask's .env
```

### C. Separate machines (production)

```
[Cloudflare Tunnel] --> [Vite :5000] --> [Flask :8000]
                                              |
                                    [MCP Server on DB host :9000]
```

Run the MCP server on the same machine as SQL Server for lowest query latency. Flask connects over the network.

---

## Testing the MCP Server Standalone

The `mcp` CLI lets you test tools without the Flask app:

```bash
# List available tools
mcp tools cobble-mcp-server/server.py

# Call a tool
mcp call cobble-mcp-server/server.py execute_sql '{"sql": "SELECT TOP 5 * FROM vw_InvOnHand"}'

# Interactive inspector (browser-based)
mcp dev cobble-mcp-server/server.py
```

This is useful for debugging tools independently of the chat UI.

---

## What Stays in Flask

After migration, `web_app.py` keeps:
- **Auth** (`@require_auth`, Clerk JWT verification)
- **Chat routes** (`/chat/stream`, `/chat`, `/conversations`)
- **Living doc routes** (`/living-docs/*`) — these are mostly MongoDB CRUD, but the refresh route calls the agent which calls MCP tools
- **O365 OAuth routes** (`/o365/*`) — the OAuth flow stays in Flask since it's user-facing
- **File download route** (`/download/*`) — serves files from shared exports dir
- **Customer specs routes** (`/customer-specs/*`) — MongoDB CRUD

What moves to MCP server:
- All 38 tool implementations
- SQL Server connectivity (pyodbc)
- Harvest Planner API client
- Excel/PDF generation
- Data catalog / learning file I/O
- O365 data access (email, calendar, OneDrive, SharePoint)

---

## Estimated Effort

| Task | Effort |
|------|--------|
| Create MCP server with dynamic tool registration | 1-2 hours |
| Copy and adapt tool modules | 1 hour |
| Rewrite agent_claude.py for MCP client | 2-3 hours |
| Test all 38 tools through MCP | 2-3 hours |
| Update deployment | 1 hour |
| **Total** | **~1 day** |

The existing `TOOL_DEFINITIONS` + `register_handlers` pattern maps almost 1:1 to MCP tool registration, which makes this migration mechanical rather than architectural.
