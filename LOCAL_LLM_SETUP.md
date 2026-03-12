# Local LLM Setup — Qwen3-32B via vLLM

Complete guide to installing, configuring, and running the Qwen3-32B data processor that sits inside the MCP server on norman-local.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  App Machine                                                        │
│                                                                     │
│  Browser ──► Vite (:5000) ──► Flask (:8000) ──► Claude API          │
│                                  │                  │               │
│                                  │           tool calls             │
│                                  │                  │               │
└──────────────────────────────────┼──────────────────┼───────────────┘
                                   │                  │
                              conversations      MCP SSE
                              (MongoDB Atlas)         │
                                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  norman-local (Compute Machine)                                     │
│                                                                     │
│  MCP Server (:9000)                                                 │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  handle_call_tool(name, arguments)                         │     │
│  │       │                                                    │     │
│  │       ▼                                                    │     │
│  │  AgentToolkit.handle_tool_call()                           │     │
│  │       │                                                    │     │
│  │       ▼                                                    │     │
│  │  Result > 500 rows? ──── NO ──► return to Claude as-is     │     │
│  │       │                                                    │     │
│  │      YES                                                   │     │
│  │       │                                                    │     │
│  │       ▼                                                    │     │
│  │  data_processor.process_result()                           │     │
│  │       │                                                    │     │
│  │       ▼                                                    │     │
│  │  Qwen3-32B (:8100) ── condense ──► summary back to Claude │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                     │
│  SQL Server (DM03/DM01)                                             │
└─────────────────────────────────────────────────────────────────────┘
```

### What lives where

| Process | Port | Machine | Role |
|---------|------|---------|------|
| Vite (React frontend) | 5000 | App machine | UI, proxies API calls |
| Flask (web_app.py) | 8000 | App machine | Auth, conversations, SSE streaming |
| Claude API | — | Anthropic cloud | Reasoning, analysis, conversation |
| MCP Server (server.py) | 9000 | norman-local | Tool execution, data processing |
| vLLM / Qwen3-32B | 8100 | norman-local | Large result summarization |
| SQL Server | 1433 | norman-local | DM03/DM01 data warehouses |

### How Claude and Qwen3 divide the work

| Responsibility | Claude | Qwen3 |
|---------------|--------|-------|
| Understand user intent | Yes | No |
| Decide which tools to call | Yes | No |
| Write SQL queries | Yes | No |
| Summarize 2,000-row query results | No | Yes |
| Analyze summarized data | Yes | No |
| Generate charts and visualizations | Yes | No |
| Talk to the user | Yes | No |
| Choose follow-up queries | Yes | No |

Claude never knows Qwen3 exists. It just sees that large query results arrive pre-summarized. The system prompt tells it to use the summary directly and re-query with `GROUP BY` or `WHERE` if it needs different detail.

---

## Hardware Requirements

Qwen3-32B in FP16 needs ~64GB VRAM. Practical options:

| Config | VRAM | Notes |
|--------|------|-------|
| 2x A100 80GB | 160GB | Overkill, but fast |
| 2x A6000 48GB | 96GB | Comfortable fit |
| 1x A100 80GB | 80GB | Tight but works with `--max-model-len 4096` |
| 4x RTX 4090 24GB | 96GB | Consumer cards, works with tensor parallelism |
| AWQ/GPTQ 4-bit quant | ~20GB | Single GPU, some quality loss |

If norman-local doesn't have enough VRAM, use a quantized version:
- `Qwen/Qwen3-32B-AWQ` — 4-bit, ~18GB VRAM, runs on a single RTX 4090
- `Qwen/Qwen3-32B-GPTQ-Int4` — similar

Update `LOCAL_LLM_MODEL` in `.env` to match whichever variant you pull.

---

## Installation

### 1. Install vLLM

On norman-local (requires Python 3.9+ and CUDA 12.1+):

```bash
pip install vllm
```

If you need a specific CUDA version:

```bash
pip install vllm --extra-index-url https://download.pytorch.org/whl/cu121
```

Verify GPU visibility:

```bash
python -c "import torch; print(f'GPUs: {torch.cuda.device_count()}')"
```

### 2. Download and serve the model

**Full precision (FP16, ~64GB VRAM):**

```bash
vllm serve Qwen/Qwen3-32B \
    --port 8100 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90
```

**Quantized (AWQ 4-bit, ~18GB VRAM):**

```bash
vllm serve Qwen/Qwen3-32B-AWQ \
    --port 8100 \
    --max-model-len 8192 \
    --quantization awq \
    --gpu-memory-utilization 0.90
```

**Multi-GPU (tensor parallelism):**

```bash
vllm serve Qwen/Qwen3-32B \
    --port 8100 \
    --tensor-parallel-size 2 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90
```

The first run downloads the model from HuggingFace (~65GB for FP16, ~18GB for AWQ). Subsequent starts load from cache (`~/.cache/huggingface/`).

### 3. Verify vLLM is running

```bash
# Check model listing
curl http://127.0.0.1:8100/v1/models

# Test inference
curl http://127.0.0.1:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-32B",
    "messages": [{"role": "user", "content": "Summarize: apples 50, oranges 30, lemons 20"}],
    "max_tokens": 256,
    "temperature": 0.1
  }'
```

You should get a JSON response with a `choices[0].message.content` field.

### 4. Enable in CobbleAI

Edit the root `.env`:

```bash
LOCAL_LLM_ENABLED = true
LOCAL_LLM_URL = http://127.0.0.1:8100
LOCAL_LLM_MODEL = Qwen/Qwen3-32B          # must match what vllm serve loaded
```

Restart the MCP server:

```bash
cd mcp && python server.py
```

You should see:

```
INFO:mcp_server:Loaded 36 tool definitions
INFO:mcp_server:Local LLM: enabled, model=Qwen/Qwen3-32B, server=reachable, threshold=500 rows
INFO:mcp_server:Starting MCP server on http://127.0.0.1:9000/sse
```

If it says `server=NOT reachable`, vLLM isn't up or the URL is wrong.

---

## Configuration Reference

All settings are in the root `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_LLM_ENABLED` | `false` | Master switch. Set `true` to activate. |
| `LOCAL_LLM_URL` | `http://127.0.0.1:8100` | vLLM server base URL |
| `LOCAL_LLM_MODEL` | `Qwen/Qwen3-32B` | Model name (must match vLLM's loaded model) |
| `LOCAL_LLM_ROW_THRESHOLD` | `500` | Row count above which results get processed |
| `LOCAL_LLM_CHAR_THRESHOLD` | `50000` | Estimated character count threshold (fallback) |
| `LOCAL_LLM_TIMEOUT` | `90` | HTTP timeout in seconds for vLLM calls |
| `LOCAL_LLM_MAX_INPUT_ROWS` | `300` | Max rows sent to Qwen3 as sample data |

### Tuning the thresholds

- **ROW_THRESHOLD=500** is conservative. Most useful queries return <200 rows when properly grouped. If Claude is writing good `GROUP BY` queries, you may never hit this.
- Lower it to **200** if you want more aggressive summarization and faster Claude responses.
- Raise it to **1000** if you find Qwen3 is processing results that Claude could have handled directly.
- **MAX_INPUT_ROWS=300** controls how much data Qwen3 sees. For 32B, 300 rows with 10 columns fits comfortably in context. Raise to 500 if you have the VRAM for longer contexts.

---

## How It Works End-to-End

### Example: "Show me all inventory by size and grade"

Without local LLM:

```
User: "Show me all inventory by size and grade"
Claude: writes SQL → SELECT Size, Grade, SUM(AvailableQuantity)... (no GROUP BY narrow enough)
SQL returns: 2,847 rows
MCP returns: 2,847 rows as JSON → Claude's context
Claude: burns ~15K tokens reading raw data, then summarizes
Total Anthropic tokens: ~20K
```

With local LLM:

```
User: "Show me all inventory by size and grade"
Claude: writes SQL → same query
SQL returns: 2,847 rows
MCP: result > 500 rows → route to Qwen3
Qwen3: condenses to markdown summary (~800 chars) with totals per commodity/size/grade
MCP returns: summary to Claude's context
Claude: reads compact summary, presents to user
Total Anthropic tokens: ~3K
```

### What Claude receives (condensed result)

```json
{
    "success": true,
    "columns": ["Size", "Grade", "Commodity", "TotalBins", "TotalCartons"],
    "rows": [],
    "row_count": 2847,
    "sql": "SELECT Size, Grade, Commodity, SUM(...) ...",
    "summary": "| Commodity | Grade | Sizes | Total Bins | Total Cartons |\n|---|---|---|---|---|\n| NAVEL | FANCY | 072,088,113,138 | 1,245 | 28,884 |\n| NAVEL | CHOICE | 072,088,113 | 832 | 19,302 |\n...",
    "processed_by": "local_llm",
    "note": "Large result (2847 rows) condensed by local processor..."
}
```

Claude sees the `summary` field and uses it directly. The `rows` array is empty — raw data never enters Claude's context.

### What happens on the Qwen3 side

The data processor builds a prompt like:

```
The user asked: "Show me all inventory by size and grade"

A SQL query returned **2847 rows** with columns: Size, Grade, Commodity, TotalBins, TotalCartons

```sql
SELECT Size, Grade, Commodity, SUM(AvailableQuantity) as TotalBins, SUM(equivctns) as TotalCartons
FROM dbo.VW_BININVENTORY WHERE AvailableQuantity > 0
GROUP BY Size, Grade, Commodity ORDER BY Commodity, Grade, Size
```

Condense this data into a summary that preserves the key information. Include:
- Aggregated totals for numeric columns (exact sums, not estimates)
- Breakdowns by the most relevant grouping columns
...

Data (300 of 2847 rows):
Size   | Grade  | Commodity | TotalBins | TotalCartons
-------|--------|-----------|-----------|-------------
072    | FANCY  | LEMON     | 45        | 1044
...
```

Qwen3 returns a compact markdown summary. The system prompt tells it to preserve exact numbers and output clean tables.

---

## Failover

The local LLM is an optimization. If it's down, slow, or returns an error, the MCP server falls back to returning raw results to Claude exactly as it did before.

```
vLLM down?        → raw result passes through, Claude handles it directly
vLLM times out?   → same — raw result, logged warning
vLLM bad output?  → same — exception caught, raw result returned
LLM disabled?     → should_process() returns False, zero overhead
```

MCP server logs will show:

```
WARNING:data_processor:Local LLM unavailable (Connection refused), returning raw result
```

No user-visible errors. Claude just gets more data to chew through — slightly slower, slightly more expensive, but fully functional.

---

## Running as a Service

Create a systemd unit for vLLM alongside the MCP server:

**`/etc/systemd/system/vllm-qwen3.service`**

```ini
[Unit]
Description=vLLM Qwen3-32B Inference Server
After=network.target

[Service]
Type=simple
User=administrator
ExecStart=/home/administrator/cobbleai/venv/bin/vllm serve Qwen/Qwen3-32B --port 8100 --max-model-len 8192 --gpu-memory-utilization 0.90
Restart=on-failure
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0,1
Environment=HF_HOME=/home/administrator/.cache/huggingface

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable vllm-qwen3
sudo systemctl start vllm-qwen3

# Check status
sudo systemctl status vllm-qwen3
journalctl -u vllm-qwen3 -f
```

The MCP server service (`cobbleai-mcp.service`) should start after vLLM:

```ini
[Unit]
Description=CobbleAI MCP Tool Server
After=network.target vllm-qwen3.service
```

Boot order: vLLM starts first → model loads into GPU → MCP server starts → health check confirms LLM is reachable.

---

## Monitoring

### Check if Qwen3 is processing results

Watch the MCP server logs:

```bash
journalctl -u cobbleai-mcp -f | grep -E "(Local LLM|Qwen3|local_llm)"
```

You'll see lines like:

```
INFO:mcp_server:Large result (2847 rows) — routing to local LLM
INFO:data_processor:Qwen3 processed 2847 rows in 4.2s (1847 chars)
```

### Check vLLM health

```bash
curl -s http://127.0.0.1:8100/v1/models | python -m json.tool
```

### Check GPU utilization

```bash
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
```

### Quick end-to-end test

```bash
cd /home/administrator/cobbleai/app
python agent_claude.py "Show me all inventory grouped by commodity, grade, and size"
```

If the local LLM is working, the agent response should arrive faster than usual for a large-result query, and the MCP logs should show the Qwen3 processing line.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `server=NOT reachable` at MCP startup | vLLM not running or wrong port | Start vLLM, check `LOCAL_LLM_URL` |
| `CUDA out of memory` on vLLM start | Not enough VRAM for model | Use quantized model (`Qwen3-32B-AWQ`) or reduce `--max-model-len` |
| Qwen3 summaries are slow (>30s) | Model too large for available GPU | Use quantized model or add `--tensor-parallel-size` |
| Summaries lose precision | Qwen3 approximating numbers | Lower `temperature` (already 0.1), check if the system prompt is being followed |
| MCP logs show "returning raw result" | vLLM crashed or OOM'd mid-inference | Check `journalctl -u vllm-qwen3`, restart if needed |
| Claude re-queries after getting summary | Summary missing info Claude needs | Increase `MAX_INPUT_ROWS`, or lower `ROW_THRESHOLD` so borderline results pass through raw |
| `Connection refused` in data_processor | vLLM process died | `sudo systemctl restart vllm-qwen3` |

---

## File Reference

| File | Purpose |
|------|---------|
| `mcp/data_processor.py` | Qwen3 client — threshold checks, prompt building, vLLM HTTP calls, fallback logic |
| `mcp/server.py` | Intercepts `execute_sql` results, routes large ones through `data_processor` |
| `app/agent_claude.py` | Attaches `_user_question` metadata to tool calls so Qwen3 knows the intent |
| `app/agent_system_prompt.md` | Tells Claude that large results may arrive pre-summarized |
| `.env` | All `LOCAL_LLM_*` configuration variables |
