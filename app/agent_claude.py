"""
DM03 Agent - Claude API + MCP Tool Server
==========================================
Orchestrates Claude conversations with tools served via MCP.

The MCP server must be running separately.
Start it with:  cd mcp && python server.py

Usage:
    cd app && python agent_claude.py "How many bins of Fancy Navels are in inventory?"
"""

import os
import sys
import json
import asyncio
import threading
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
from mcp.client.sse import sse_client
from mcp import ClientSession

# Load .env from repo root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Initialize
client = Anthropic()

# Config from .env
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TURNS = int(os.getenv("MAX_AGENT_TURNS", "10"))
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:9000/sse")

# Load system prompt (relative to this file)
_PROMPT_PATH = Path(__file__).resolve().parent / "agent_system_prompt.md"
with open(_PROMPT_PATH, "r") as f:
    SYSTEM_PROMPT = f.read()


# ── MCP Connection ───────────────────────────────────────────────────────────

_tools_cache = None
_tools_cache_lock = threading.Lock()


async def _fetch_tools_from_mcp() -> list[dict]:
    """Connect to MCP server and fetch tool definitions."""
    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema,
                }
                for t in result.tools
            ]


def get_tools() -> list[dict]:
    """Get tool definitions from MCP server (cached after first call)."""
    global _tools_cache
    with _tools_cache_lock:
        if _tools_cache is None:
            _tools_cache = asyncio.run(_fetch_tools_from_mcp())
    return _tools_cache


def refresh_tools():
    """Force re-fetch tools from MCP server."""
    global _tools_cache
    with _tools_cache_lock:
        _tools_cache = None


async def _call_tool_mcp(name: str, arguments: dict) -> str:
    """Call a single tool on the MCP server and return the result as JSON string."""
    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            # Extract text content from MCP result
            if result.content:
                parts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                return "\n".join(parts) if parts else "{}"
            return "{}"


def call_tool(name: str, arguments: dict) -> str:
    """Sync wrapper to call an MCP tool. Returns JSON string."""
    return asyncio.run(_call_tool_mcp(name, arguments))


# ── Async MCP session for batch tool calls ───────────────────────────────────

async def _call_tools_batch(calls: list[tuple[str, dict]]) -> list[str]:
    """Call multiple tools in a single MCP session."""
    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = []
            for name, arguments in calls:
                result = await session.call_tool(name, arguments)
                if result.content:
                    parts = []
                    for block in result.content:
                        if hasattr(block, "text"):
                            parts.append(block.text)
                    results.append("\n".join(parts) if parts else "{}")
                else:
                    results.append("{}")
            return results


# ── Agent turns ──────────────────────────────────────────────────────────────

def _latest_user_text(messages: list) -> str:
    """Extract the most recent user message text for local LLM context."""
    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            return msg["content"][:500]
    return ""


def run_agent_turn(messages: list, max_turns: int = None, log_fn=None, user_id: str = None) -> str:
    """
    Run the agent for one user question, continuing the conversation in messages.
    Messages list is mutated in place to preserve history for follow-ups.
    """
    if log_fn is None:
        log_fn = print
    max_turns = max_turns or MAX_TURNS
    tools = get_tools()
    accumulated_text = []
    user_question = _latest_user_text(messages)

    for turn in range(max_turns):
        with client.messages.stream(
            model=MODEL,
            max_tokens=30000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        ) as stream:
            response = stream.get_final_message()

        for block in response.content:
            if hasattr(block, "text") and block.text.strip():
                accumulated_text.append(block.text)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return "\n".join(accumulated_text) if accumulated_text else "No response generated."

        # Collect all tool calls for this turn
        pending_calls = []
        for block in response.content:
            if block.type == "tool_use":
                log_fn(f"  [Tool Call] {block.name}: {json.dumps(block.input)[:100]}...")
                params = dict(block.input)
                if user_id:
                    params["_user_id"] = user_id
                params["_user_question"] = user_question
                pending_calls.append((block, params))

        # Execute all tool calls in a single MCP session
        if pending_calls:
            call_args = [(b.name, p) for b, p in pending_calls]
            results = asyncio.run(_call_tools_batch(call_args))

            tool_results = []
            for (block, _), result_str in zip(pending_calls, results):
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str
                })
            messages.append({"role": "user", "content": tool_results})

    return "\n".join(accumulated_text) if accumulated_text else "Max turns reached without final response."


def run_agent_turn_streaming(messages: list, max_turns: int = None, log_fn=None, user_id: str = None):
    """
    Generator version that yields SSE events.
    Yields (event_type, payload) tuples: ("token", text) or ("tool", name).
    """
    if log_fn is None:
        log_fn = print
    max_turns = max_turns or MAX_TURNS
    tools = get_tools()
    user_question = _latest_user_text(messages)

    for turn in range(max_turns):
        with client.messages.stream(
            model=MODEL,
            max_tokens=30000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        ) as stream:
            for event in stream:
                if hasattr(event, 'type'):
                    if event.type == 'content_block_delta' and hasattr(event.delta, 'text'):
                        yield ("token", event.delta.text)
            response = stream.get_final_message()

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return

        # Collect tool calls
        pending_calls = []
        for block in response.content:
            if block.type == "tool_use":
                log_fn(f"  [Tool Call] {block.name}: {json.dumps(block.input)[:100]}...")
                yield ("tool", block.name)
                params = dict(block.input)
                if user_id:
                    params["_user_id"] = user_id
                params["_user_question"] = user_question
                pending_calls.append((block, params))

        # Execute all tool calls in a single MCP session
        if pending_calls:
            call_args = [(b.name, p) for b, p in pending_calls]
            results = asyncio.run(_call_tools_batch(call_args))

            tool_results = []
            for (block, _), result_str in zip(pending_calls, results):
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str
                })
            messages.append({"role": "user", "content": tool_results})


# ── CLI ──────────────────────────────────────────────────────────────────────

def run_agent(user_question: str, max_turns: int = None) -> str:
    """Run a single standalone question (no conversation history)."""
    messages = [{"role": "user", "content": user_question}]
    return run_agent_turn(messages, max_turns)


def interactive_mode():
    """Run in interactive chat mode with conversation history."""
    print("DM03 Data Warehouse Agent (MCP)")
    print("=" * 50)
    print("Ask questions about inventory, receiving, sales, growers, etc.")
    print("Follow-up questions use prior responses as context.")
    print("Type 'new' to start a fresh conversation.")
    print("Type 'exit' to quit.\n")

    conversation = []

    while True:
        try:
            question = input("\nYou: ").strip()
            if question.lower() in ('exit', 'quit', 'q'):
                break
            if not question:
                continue
            if question.lower() == 'new':
                conversation = []
                print("\n--- New conversation started ---")
                continue

            conversation.append({"role": "user", "content": question})
            print("\nAgent thinking...\n")
            response = run_agent_turn(conversation)
            print(f"\nAgent: {response}")

        except KeyboardInterrupt:
            break

    print("\nGoodbye!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"Question: {question}\n")
        response = run_agent(question)
        print(f"\nAnswer:\n{response}")
    else:
        interactive_mode()
