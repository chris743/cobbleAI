"""Local LLM data processor — condenses large query results via Qwen3-32B (vLLM).

When a SQL query returns more rows than the configured threshold, this module
sends the result to a local Qwen3-32B instance for summarization before it
reaches Claude. This saves Anthropic API tokens and keeps Claude's context
focused on analysis rather than raw data.

The local LLM runs via vLLM which exposes an OpenAI-compatible API:
    vllm serve Qwen/Qwen3-32B --port 8100

If the local LLM is unavailable, processing is skipped and the raw result
passes through unchanged.
"""

import os
import json
import logging
import time

import httpx

log = logging.getLogger("data_processor")

# ── Config ────────────────────────────────────────────────────────────────────

ENABLED = os.getenv("LOCAL_LLM_ENABLED", "false").lower() in ("true", "1", "yes")
VLLM_BASE_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8100")
VLLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen3-32B")
ROW_THRESHOLD = int(os.getenv("LOCAL_LLM_ROW_THRESHOLD", "500"))
CHAR_THRESHOLD = int(os.getenv("LOCAL_LLM_CHAR_THRESHOLD", "50000"))
TIMEOUT = int(os.getenv("LOCAL_LLM_TIMEOUT", "90"))
MAX_INPUT_ROWS = int(os.getenv("LOCAL_LLM_MAX_INPUT_ROWS", "150"))
MAX_PROMPT_CHARS = int(os.getenv("LOCAL_LLM_MAX_PROMPT_CHARS", "55000"))  # ~20K tokens, leaves room for 4K output within 32K context

_client = httpx.Client(base_url=VLLM_BASE_URL, timeout=TIMEOUT)


# ── Public API ────────────────────────────────────────────────────────────────

def should_process(result: dict) -> bool:
    """Check if a query result is large enough to warrant local LLM processing."""
    if not ENABLED:
        return False
    if not result.get("success"):
        return False

    row_count = result.get("row_count", 0)
    if row_count > ROW_THRESHOLD:
        return True

    # Estimate serialized size without actually serializing the full thing
    data_chars = _estimate_size(result)
    if data_chars > CHAR_THRESHOLD:
        return True

    return False


def process_result(result: dict, user_question: str = "") -> dict:
    """Condense a large SQL result via the local Qwen3-32B.

    Returns a modified result dict. On any error, returns the original
    result unchanged (the local LLM is an optimization, not a dependency).
    """
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    row_count = result.get("row_count", 0)
    sql = result.get("sql", "")

    # Build a data sample for Qwen — full data up to MAX_INPUT_ROWS
    sample_rows = rows[:MAX_INPUT_ROWS]
    sample_text = _format_rows(columns, sample_rows)
    remainder = row_count - len(sample_rows)

    prompt = _build_prompt(user_question, sql, columns, row_count, sample_text, remainder)

    try:
        t0 = time.time()
        summary = _call_vllm(prompt)
        elapsed = time.time() - t0
        log.info(f"Qwen3 processed {row_count} rows in {elapsed:.1f}s ({len(summary)} chars)")
    except Exception as e:
        log.warning(f"Local LLM unavailable ({e}), returning raw result")
        return result

    return {
        "success": True,
        "columns": columns,
        "rows": [],
        "row_count": row_count,
        "sql": sql,
        "truncated": result.get("truncated", False),
        "summary": summary,
        "processed_by": "local_llm",
        "note": f"Large result ({row_count} rows) condensed by local processor. "
                f"Raw data omitted to save context. If Claude needs specific rows, "
                f"re-query with a narrower WHERE clause or GROUP BY.",
    }


# ── vLLM client ───────────────────────────────────────────────────────────────

def _call_vllm(prompt: str) -> str:
    """Call Qwen3-32B via vLLM's OpenAI-compatible chat endpoint."""
    response = _client.post("/v1/chat/completions", json={
        "model": VLLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a data processing assistant. Your job is to condense "
                    "large SQL query results into compact, accurate summaries. "
                    "Preserve exact numbers — never approximate totals. "
                    "Output clean markdown tables when the data is tabular. "
                    "Keep your output under 3000 characters."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
    })
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def is_available() -> bool:
    """Check if the local LLM server is reachable."""
    if not ENABLED:
        return False
    try:
        r = _client.get("/v1/models", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ── Prompt construction ───────────────────────────────────────────────────────

def _build_prompt(user_question: str, sql: str, columns: list,
                  row_count: int, sample_text: str, remainder: int) -> str:
    parts = []

    if user_question:
        parts.append(f'The user asked: "{user_question}"')
    parts.append(f"A SQL query returned **{row_count} rows** with columns: {', '.join(columns)}")

    if sql:
        parts.append(f"```sql\n{sql}\n```")

    parts.append(
        "Condense this data into a summary that preserves the key information. Include:\n"
        "- Aggregated totals for numeric columns (exact sums, not estimates)\n"
        "- Breakdowns by the most relevant grouping columns\n"
        "- Top/bottom items if the data is a ranked list\n"
        "- Row counts per group when relevant\n"
        "- Notable outliers or zero values worth calling out\n\n"
        "Use markdown tables for structured output. "
        "Do NOT include any commentary — just the condensed data."
    )

    parts.append(f"Data ({min(row_count, len(sample_text.splitlines()) - 2)} of {row_count} rows):")
    parts.append(sample_text)

    if remainder > 0:
        parts.append(f"... plus {remainder} more rows not shown.")

    prompt = "\n\n".join(parts)

    # Hard cap to stay within Qwen3-32B's 32K context (~2.7 chars/token)
    if len(prompt) > MAX_PROMPT_CHARS:
        log.info(f"Prompt too long ({len(prompt)} chars), truncating to {MAX_PROMPT_CHARS}")
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n\n... [data truncated to fit context window]"

    return prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_rows(columns: list, rows: list) -> str:
    """Format rows as a pipe-delimited text table."""
    if not rows:
        return "(no data)"

    # Compute column widths for readability (capped)
    widths = [min(len(str(c)), 30) for c in columns]
    for row in rows[:50]:  # sample first 50 for width calculation
        for i, v in enumerate(row):
            if i < len(widths):
                widths[i] = min(max(widths[i], len(str(v) if v is not None else "")), 30)

    header = " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns))
    separator = "-|-".join("-" * w for w in widths)

    lines = [header, separator]
    for row in rows:
        line = " | ".join(
            str(v if v is not None else "").ljust(widths[i]) if i < len(widths)
            else str(v if v is not None else "")
            for i, v in enumerate(row)
        )
        lines.append(line)

    return "\n".join(lines)


def _estimate_size(result: dict) -> int:
    """Rough estimate of result size in characters without full serialization."""
    rows = result.get("rows", [])
    if not rows:
        return 0
    # Sample first 10 rows, extrapolate
    sample = rows[:10]
    sample_str = json.dumps(sample, default=str)
    avg_row_size = len(sample_str) / max(len(sample), 1)
    return int(avg_row_size * len(rows))
