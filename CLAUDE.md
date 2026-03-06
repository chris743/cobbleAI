# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CobbleAI is a Python-based AI data warehouse agent for a citrus packing operation. It provides a web chat interface for querying the DM03/DM01 data warehouses and managing harvest planning data via a REST API.

## Tech Stack

- **Backend**: Flask 3.1.3 (Python 3)
- **AI**: Anthropic Claude API (`anthropic` SDK) with agentic tool-calling loop
- **Database**: Microsoft SQL Server via pyodbc (ODBC Driver 17)
- **Frontend**: Single-page HTML/JS with marked.js (markdown) and Chart.js (visualization)
- **Config**: `.env` file loaded via python-dotenv

## Running the App

```bash
# Install dependencies (use the existing venv)
pip install -r requirements.txt

# Start the web server (http://localhost:5000)
python web_app.py
```

There are no tests, linter, or CI pipeline configured.

## Architecture

### Entry Points

- `web_app.py` — Flask server with routes: `GET /`, `POST /chat`, `POST /new`, `GET /download/<filename>`
- `agent_claude.py` — Agent orchestration: initializes Claude client, runs the agentic tool-calling loop via `run_agent_turn(messages, log_fn)`
- `agent_tools.py` (~1050 lines) — All 26 tool definitions and implementations

### Agent Tool System (agent_tools.py)

The file contains several subsystems bundled together:

- **QueryExecutor** — Read-only SQL execution against DM03 (operations) or DM01 (harvest planning). Validates queries are SELECT/WITH only, blocks forbidden keywords, limits to 5000 rows.
- **ContextLoader** — Loads YAML-based schema docs from `data-catalog/` for table lookups and full-text search.
- **LearningManager** — Persists successful query patterns, user corrections, and data discoveries to YAML files in `agent-learning/`.
- **ExcelExporter** — Generates `.xlsx` files into `exports/` directory.
- **HarvestPlannerAPI** — HTTP client for external Harvest Planner REST API with JWT auth and token refresh.

### Key Data Flow

1. User sends message via chat UI → `POST /chat`
2. `web_app.py` appends to in-memory conversation history (dict keyed by conversation_id)
3. `run_agent_turn()` sends messages + system prompt to Claude API
4. Claude responds with tool calls; agent loop executes tools and feeds results back
5. Final text response returned to frontend, rendered as markdown

### System Prompt & Data Catalog

- `agent_system_prompt.md` (~330 lines) — Comprehensive operational rules, query patterns, business context, and visualization instructions
- `data-catalog/` — YAML files documenting database schemas, organized by domain:
  - `domains/` — Per-domain table schemas (inventory, sales, harvest, labor, packout, products, receiving, repacking)
  - `glossary.yaml` — Business terminology (Bin, Carton, Style, Grade, etc.)
  - `size_dictionary.yaml` — Valid fruit sizes by commodity
  - `system_architecture.yaml` — Database schema rules and join patterns
  - `agent_context.md` — Available tables reference
- `api_connections/HARVEST_PLANNER_CONTEXT.md` — Harvest Planner API documentation

### Multi-Database Pattern

The agent operates across two databases:
- **DM03** — Main operations data (inventory, sales, packout, receiving, labor)
- **DM01** — Harvest planning data

`QueryExecutor` accepts a `database` parameter to switch between them.

## Key Business Concepts

- **Bin**: Bulk container (~23.2 cartons for most commodities, 37.5 for mandarins)
- **Carton**: Standard shipping unit (40 lbs, except mandarins at 25 lbs)
- **Style**: Packaging format that determines equipment line (FB, CB, NB, WM, HD, Bulk)
- **Size**: Always 3-digit zero-padded strings (e.g., `'088'`)
- **Source systems**: Cobblestone (CF) for grower accounting, LP for inventory/packing/sales — critical for understanding join patterns

## Important Conventions

- SQL queries must be read-only (SELECT/WITH). Forbidden keywords are validated in `QueryExecutor`.
- The agent learning files (`agent-learning/*.yaml`) are append-only during runtime.
- Excel exports go to `exports/` with UUID-based filenames.
- Conversations are stored in-memory only (lost on restart).
- The `.env` file contains API keys and database credentials — never commit it.
