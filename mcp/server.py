"""CobbleAI MCP Tool Server.

Exposes all agent tools via MCP protocol (SSE transport).
Run standalone:  cd mcp && python server.py
"""

import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Ensure mcp/ is on sys.path so tools can import sibling modules (living_docs, o365_auth, etc.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp.types as types
from mcp.server.lowlevel import Server, NotificationOptions
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response, FileResponse
import uvicorn

from tools import AgentToolkit
from tools.user_context import set_user_id
import data_processor

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mcp_server")

MCP_PORT = int(os.getenv("MCP_PORT", "9000"))

toolkit = AgentToolkit()
tool_defs = toolkit.get_tool_definitions()

# Build MCP Tool objects from our toolkit definitions
_mcp_tools = []
for td in tool_defs:
    _mcp_tools.append(types.Tool(
        name=td["name"],
        description=td["description"],
        inputSchema=td["parameters"],
    ))

log.info(f"Loaded {len(_mcp_tools)} tool definitions")
if data_processor.ENABLED:
    avail = data_processor.is_available()
    log.info(f"Local LLM: enabled, model={data_processor.VLLM_MODEL}, "
             f"server={'reachable' if avail else 'NOT reachable'}, "
             f"threshold={data_processor.ROW_THRESHOLD} rows")
else:
    log.info("Local LLM: disabled (set LOCAL_LLM_ENABLED=true to activate)")

# ── Low-level MCP server ─────────────────────────────────────────────────────

server = Server("CobbleAI Tools")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return _mcp_tools


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    arguments = arguments or {}

    # Extract metadata before dispatching to tool handlers
    user_id = arguments.pop("_user_id", None)
    user_question = arguments.pop("_user_question", "")
    if user_id:
        set_user_id(user_id)

    log.info(f"Tool call: {name} — {json.dumps(arguments, default=str)[:200]}")

    try:
        result = toolkit.handle_tool_call(name, arguments)

        # Post-process large SQL results through local Qwen3
        if name in ("execute_sql", "query_to_excel") and isinstance(result, dict):
            if data_processor.should_process(result):
                log.info(f"Large result ({result.get('row_count', 0)} rows) — routing to local LLM")
                result = data_processor.process_result(result, user_question)

        result_str = json.dumps(result, default=str)
    except Exception as e:
        log.exception(f"Error in tool {name}")
        result_str = json.dumps({"error": str(e)})

    return [types.TextContent(type="text", text=result_str)]


# ── SSE transport via Starlette ───────────────────────────────────────────────

sse = SseServerTransport("/messages/")


async def handle_sse(request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(tools_changed=False)
            ),
        )
    return Response()


EXPORTS_DIR = Path(__file__).resolve().parent / "exports"

_DOWNLOAD_MIMETYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
}


async def handle_download(request):
    """Serve exported files (Excel/PDF) from mcp/exports/."""
    filename = request.path_params["filename"]
    # Block path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return Response("Not found", status_code=404)
    ext = os.path.splitext(filename)[1].lower()
    mimetype = _DOWNLOAD_MIMETYPES.get(ext)
    if not mimetype:
        return Response("Not found", status_code=404)
    filepath = EXPORTS_DIR / filename
    if not filepath.is_file():
        return Response("Not found", status_code=404)
    return FileResponse(filepath, media_type=mimetype, filename=filename)


app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
        Route("/download/{filename}", endpoint=handle_download),
    ],
)


if __name__ == "__main__":
    log.info(f"Starting MCP server on http://0.0.0.0:{MCP_PORT}/sse")
    uvicorn.run(app, host="0.0.0.0", port=MCP_PORT, log_level="info")
