# Local LLM Integration — Qwen3-32B for Data Processing

> **Status: Implemented.** Code is in place, disabled by default. Set `LOCAL_LLM_ENABLED=true` in `.env` and start vLLM to activate.

## Problem

Claude has a context window and per-token cost. When the agent runs a SQL query that returns 3,000+ rows, that entire result set gets stuffed into Claude's context as a tool result. This is:

1. **Expensive** — large tool results burn tokens on every subsequent turn
2. **Slow** — streaming a 50KB tool result through the Anthropic API adds latency
3. **Wasteful** — Claude doesn't need to see every row to answer "what's the total inventory by commodity"

## Proposed Solution

Add a local Qwen3 instance as a **data processing layer** between the MCP tools and Claude. Large query results get summarized/transformed by Qwen3 before Claude ever sees them. Claude stays the analyst and conversationalist — Qwen3 is the data grunt.

```
User question
    │
    ▼
Claude (Anthropic API)          ← reasoning, analysis, conversation
    │
    │ tool call: execute_sql
    ▼
MCP Server
    │
    │ SQL result: 4,200 rows
    ▼
Size check: result > threshold?
    │
    ├─ NO  → return raw result to Claude (small enough)
    │
    └─ YES → send to Qwen3 with a processing instruction
              │
              ▼
         Qwen3 (local)           ← summarize, aggregate, extract
              │
              ▼
         Condensed result → return to Claude
```

## What Qwen3 Handles

Qwen3 processes **data**, not decisions. Examples:

| Scenario | Raw Result | Qwen3 Output |
|----------|-----------|---------------|
| "Show inventory by commodity" | 4,200 rows of bin-level detail | Aggregated table: 8 commodities with totals |
| "List all sales orders this week" | 1,800 order lines | Summary: 342 orders, top 10 customers, total revenue |
| "What sizes are we packing for Walmart?" | 600 packout records | Distinct size list by commodity with volume |
| "Compare this week vs last week" | Two 2,000-row result sets | Side-by-side delta table, key changes highlighted |

Qwen3 does NOT:
- Decide what queries to run (Claude does that)
- Talk to the user (Claude does that)
- Make business recommendations (Claude does that)
- Choose visualization types (Claude does that)

## Architecture

### Where Qwen3 Runs

On the same machine as the MCP server (norman-local). It already has the compute resources and database access. The local LLM stays internal — no data leaves the network.

```
norman-local (compute machine)
├── MCP Server (port 9000)       ← tool execution
├── Qwen3 (port 11434 or similar) ← local inference via Ollama/vLLM/llama.cpp
└── SQL Server (DM03/DM01)       ← data
```

### Integration Point

The processing happens inside the MCP server, specifically in the tool handlers. The MCP server already owns the tool results — it just optionally passes large ones through Qwen3 before returning them to Claude.

**New module: `mcp/data_processor.py`**

```python
"""Local LLM data processor for large query results."""

import os
import httpx

QWEN_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/generate")
QWEN_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen3")
ROW_THRESHOLD = int(os.getenv("LOCAL_LLM_ROW_THRESHOLD", "500"))
CHAR_THRESHOLD = int(os.getenv("LOCAL_LLM_CHAR_THRESHOLD", "50000"))


def should_process(result: dict) -> bool:
    """Decide if a query result is large enough to warrant local processing."""
    rows = result.get("row_count", 0)
    data_size = len(str(result.get("data", "")))
    return rows > ROW_THRESHOLD or data_size > CHAR_THRESHOLD


def process_large_result(result: dict, user_question: str) -> dict:
    """
    Send a large query result to the local LLM for condensing.
    Returns a modified result dict with summarized data.
    """
    raw_data = result.get("data", [])
    columns = result.get("columns", [])
    row_count = result.get("row_count", 0)

    prompt = f"""You are a data processing assistant. The user asked: "{user_question}"

A SQL query returned {row_count} rows with columns: {columns}

Your job: condense this data into a compact summary that preserves the key information needed to answer the question. Include:
- Aggregated totals where appropriate
- Top/bottom items if the list is long
- Key breakdowns by the most relevant grouping columns
- Any notable outliers or patterns

Return the summary as a clean markdown table or structured text. Keep it under 2000 characters.

Raw data (first 200 rows shown):
{_format_rows(columns, raw_data[:200])}

{f"... and {row_count - 200} more rows" if row_count > 200 else ""}"""

    response = httpx.post(QWEN_URL, json={
        "model": QWEN_MODEL,
        "prompt": prompt,
        "stream": False,
    }, timeout=60.0)

    summary = response.json().get("response", "")

    return {
        "columns": columns,
        "data": [],  # raw data stripped
        "row_count": row_count,
        "summary": summary,
        "note": f"Result condensed from {row_count} rows by local processor",
    }


def _format_rows(columns: list, rows: list) -> str:
    """Format rows as a compact text table."""
    if not rows:
        return "(no data)"
    header = " | ".join(str(c) for c in columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)
```

### Hook into QueryExecutor

The processing wraps the existing `execute_sql` tool handler in the MCP server. Two options:

**Option A — Transparent in MCP server (recommended)**

Modify `mcp/server.py` to intercept `execute_sql` results:

```python
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None):
    # ... existing dispatch ...
    result = toolkit.handle_tool_call(name, arguments)

    # Post-process large SQL results
    if name == "execute_sql" and isinstance(result, dict):
        from data_processor import should_process, process_large_result
        if should_process(result):
            user_hint = arguments.get("_user_question", "")
            result = process_large_result(result, user_hint)

    return [types.TextContent(type="text", text=json.dumps(result, default=str))]
```

**Option B — Dedicated tool**

Add a `process_data` tool that Claude can explicitly call when it knows the result will be large. Claude would call `execute_sql` → see it's huge → call `process_data` with the result. This gives Claude control but adds a turn.

Option A is better because it's invisible to Claude and saves a full round-trip.

### Passing the User Question

For Qwen3 to summarize effectively, it needs to know what the user actually asked. The user's question should propagate through the chain:

```
agent_claude.py                  → passes user_question in tool args
  └─ MCP tool call: execute_sql
       args: {sql: "...", _user_question: "what's our navel inventory?"}
            └─ MCP server intercepts, passes to Qwen3
```

Add `_user_question` as a metadata field (like the existing `_user_id`), stripped before reaching the actual SQL executor.

## New .env Variables

```
# Local LLM (Qwen3)
LOCAL_LLM_URL=http://127.0.0.1:11434/api/generate
LOCAL_LLM_MODEL=qwen3
LOCAL_LLM_ROW_THRESHOLD=500          # rows before triggering summarization
LOCAL_LLM_CHAR_THRESHOLD=50000       # characters before triggering
LOCAL_LLM_ENABLED=true               # kill switch
```

## What Changes in Each Layer

| Component | Change |
|-----------|--------|
| `mcp/server.py` | Intercept large `execute_sql` results, route through `data_processor.py` |
| `mcp/data_processor.py` | **New** — Qwen3 client, threshold logic, prompt construction |
| `app/agent_claude.py` | Pass `_user_question` metadata alongside `_user_id` in tool call args |
| `app/agent_system_prompt.md` | Update to tell Claude that large results may arrive pre-summarized |
| `.env` | Add `LOCAL_LLM_*` variables |
| norman-local | Run Qwen3 via Ollama (`ollama serve` + `ollama pull qwen3`) |

No changes to the frontend, auth, or conversation storage.

## Running Qwen3

The simplest path is Ollama:

```bash
# On norman-local
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen3          # or qwen3:14b, qwen3:32b depending on VRAM
ollama serve               # default: http://127.0.0.1:11434
```

Ollama exposes an OpenAI-compatible API at `/api/generate` and `/v1/chat/completions`. The `data_processor.py` module talks to it directly via HTTP — no SDK needed.

For higher throughput or GPU optimization, vLLM is an alternative:

```bash
pip install vllm
vllm serve Qwen/Qwen3-14B --port 11434
```

## Fallback Behavior

If Qwen3 is unavailable (down, slow, error), the MCP server falls back to returning the raw result to Claude as it does today. The local LLM is an optimization, not a dependency.

```python
def process_large_result(result, user_question):
    try:
        # ... call Qwen3 ...
    except Exception:
        log.warning("Local LLM unavailable, returning raw result")
        return result  # passthrough
```

## Future Extensions

- **Query planning**: Qwen3 pre-processes the user question to suggest better SQL (GROUP BY instead of returning all rows), reducing the data volume before it even hits the database
- **Multi-step processing**: Qwen3 handles data joins and transformations that would be awkward in SQL
- **Caching**: Hash the SQL + result, skip Qwen3 if the same query was processed recently
- **Streaming**: For very large results, Qwen3 streams its summary back so the user isn't waiting on a full batch
