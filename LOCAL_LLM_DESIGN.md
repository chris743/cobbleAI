# Local LLM Integration — Qwen3-32B for Data Processing

> **Status: Implemented.** Code is in place, disabled by default. Set `LOCAL_LLM_ENABLED=true` in `.env` and start vLLM to activate. See `LOCAL_LLM_SETUP.md` for install and ops guide.

## Problem

Claude has a context window and per-token cost. When the agent runs a SQL query that returns 3,000+ rows, that entire result set gets stuffed into Claude's context as a tool result. This is:

1. **Expensive** — large tool results burn tokens on every subsequent turn
2. **Slow** — streaming a 50KB tool result through the Anthropic API adds latency
3. **Wasteful** — Claude doesn't need to see every row to answer "what's the total inventory by commodity"

## Solution

A local Qwen3-32B instance acts as a **data processing layer** between the MCP tools and Claude. Large query results get summarized/transformed by Qwen3 before Claude ever sees them. Claude stays the analyst and conversationalist — Qwen3 is the data grunt.

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
         Qwen3-32B (local)      ← summarize, aggregate, extract
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
├── vLLM + Qwen3-32B (port 8100) ← local inference, OpenAI-compatible API
└── SQL Server (DM03/DM01)       ← data
```

### Integration Point

The processing happens inside the MCP server, in the `handle_call_tool` handler. After `execute_sql` returns, the server checks the result size. If it exceeds the threshold, `data_processor.process_result()` sends it to Qwen3 via vLLM's `/v1/chat/completions` endpoint and returns the condensed summary to Claude instead of the raw rows.

**Module: `mcp/data_processor.py`**

```python
VLLM_BASE_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8100")
VLLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen3-32B")
ROW_THRESHOLD = int(os.getenv("LOCAL_LLM_ROW_THRESHOLD", "500"))

_client = httpx.Client(base_url=VLLM_BASE_URL, timeout=90)

def _call_vllm(prompt: str) -> str:
    response = _client.post("/v1/chat/completions", json={
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a data processing assistant..."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048,
        "temperature": 0.1,
    })
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
```

### Hook into MCP Server

The processing is transparent — intercepted in `mcp/server.py` after tool dispatch:

```python
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None):
    # ... existing dispatch ...
    result = toolkit.handle_tool_call(name, arguments)

    # Post-process large SQL results through local Qwen3
    if name in ("execute_sql", "query_to_excel") and isinstance(result, dict):
        if data_processor.should_process(result):
            result = data_processor.process_result(result, user_question)

    return [types.TextContent(type="text", text=json.dumps(result, default=str))]
```

Invisible to Claude. No extra tool call round-trip.

### Passing the User Question

For Qwen3 to summarize effectively, it needs to know what the user actually asked. `agent_claude.py` attaches the latest user message as `_user_question` metadata on every tool call (alongside the existing `_user_id`). The MCP server strips it before reaching the actual tool handler and passes it to `data_processor`.

```
agent_claude.py                  → passes _user_question in tool args
  └─ MCP tool call: execute_sql
       args: {sql: "...", _user_question: "what's our navel inventory?"}
            └─ MCP server strips metadata, passes question to Qwen3
```

## .env Variables

```
# Local LLM (Qwen3-32B via vLLM)
LOCAL_LLM_ENABLED=true               # master switch
LOCAL_LLM_URL=http://127.0.0.1:8100  # vLLM server
LOCAL_LLM_MODEL=Qwen/Qwen3-32B      # must match vllm serve model name
LOCAL_LLM_ROW_THRESHOLD=500          # rows before triggering summarization
LOCAL_LLM_CHAR_THRESHOLD=50000       # estimated characters before triggering
LOCAL_LLM_TIMEOUT=90                 # seconds
LOCAL_LLM_MAX_INPUT_ROWS=300         # max rows sent as sample to Qwen3
```

## What Changes in Each Layer

| Component | Change |
|-----------|--------|
| `mcp/data_processor.py` | **New** — vLLM client, threshold logic, prompt construction, fallback |
| `mcp/server.py` | Intercept large `execute_sql` results, route through `data_processor` |
| `app/agent_claude.py` | Pass `_user_question` metadata alongside `_user_id` in tool call args |
| `app/agent_system_prompt.md` | Tell Claude that large results may arrive pre-summarized |
| `.env` | Add `LOCAL_LLM_*` variables |
| norman-local | Run vLLM with Qwen3-32B on port 8100 |

No changes to the frontend, auth, or conversation storage.

## Running Qwen3

```bash
# Install vLLM
pip install vllm

# Serve Qwen3-32B (FP16 — needs ~64GB VRAM)
vllm serve Qwen/Qwen3-32B --port 8100 --max-model-len 8192

# Or quantized (AWQ 4-bit — needs ~18GB VRAM)
vllm serve Qwen/Qwen3-32B-AWQ --port 8100 --max-model-len 8192 --quantization awq

# Or multi-GPU
vllm serve Qwen/Qwen3-32B --port 8100 --tensor-parallel-size 2 --max-model-len 8192
```

vLLM exposes an OpenAI-compatible API at `/v1/chat/completions`. The `data_processor.py` module talks to it directly via httpx — no SDK needed.

## Fallback Behavior

If Qwen3 is unavailable (down, slow, error), the MCP server falls back to returning the raw result to Claude as it does today. The local LLM is an optimization, not a dependency.

```python
def process_result(result, user_question):
    try:
        summary = _call_vllm(prompt)
    except Exception as e:
        log.warning(f"Local LLM unavailable ({e}), returning raw result")
        return result  # passthrough
```

## Future Extensions

- **Query planning**: Qwen3 pre-processes the user question to suggest better SQL (GROUP BY instead of returning all rows), reducing the data volume before it even hits the database
- **Multi-step processing**: Qwen3 handles data joins and transformations that would be awkward in SQL
- **Caching**: Hash the SQL + result, skip Qwen3 if the same query was processed recently
- **Streaming**: For very large results, Qwen3 streams its summary back so the user isn't waiting on a full batch
