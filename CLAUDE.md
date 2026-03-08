# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CobbleAI is a Python-based AI data warehouse agent for a citrus packing operation. It provides a web chat interface for querying the DM03/DM01 data warehouses and managing harvest planning data via a REST API.

## Tech Stack

- **Backend**: Flask 3.1 (Python 3), served via Gunicorn (`--timeout 300 --workers 3`) on port 8000
- **AI**: Anthropic Claude API (`anthropic` SDK) with agentic tool-calling loop, streaming via SSE
- **Database**: Microsoft SQL Server via pyodbc (ODBC Driver 17)
- **Persistence**: MongoDB Atlas (`chat_store.py`) for conversation history
- **Auth**: Clerk — React frontend (`@clerk/react`), backend JWT/JWKS verification (`auth.py`)
- **Frontend**: React (Vite) on port 5000 with marked.js (markdown) and Chart.js (visualization)
- **Config**: `.env` file loaded via python-dotenv

## Running the App

```bash
# Backend
pip install -r requirements.txt
python web_app.py                    # Dev: http://localhost:8000
# Production: gunicorn web_app:app -b 0.0.0.0:8000 --timeout 300 --workers 3

# Frontend
cd norman_frontend
npm install
npm run dev                          # Dev: http://localhost:5000 (proxies API to :8000)
npm run build                        # Production build
npm run lint                         # ESLint

# Agent CLI (bypasses web/auth — useful for debugging tools directly)
python agent_claude.py "How many bins of Fancy Navels are in inventory?"   # single question
python agent_claude.py                                                      # interactive REPL

# DB connectivity check
python db_test.py
```

There are no automated tests or CI pipeline configured.

## Required .env Variables

```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-20250514   # optional override
MAX_AGENT_TURNS=10                          # optional override
DB_SERVER=RDGW-CF
DB_DATABASE=DM03
DB_USERNAME=
DB_PASSWORD=
DB_TRUSTED_CONNECTION=yes                  # set to 'no' for SQL auth
QUERY_TIMEOUT=30
MAX_ROWS=5000
CONTEXT_PATH=./data-catalog
LEARNING_PATH=./agent-learning
CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
MONGODB_URI=
HARVEST_PLANNER_BASE_URL=
HARVEST_PLANNER_USERNAME=
HARVEST_PLANNER_PASSWORD=
```

## Architecture

### Entry Points

- `web_app.py` — Flask API server (port 8000). Routes: `POST /chat/stream` (SSE), `POST /chat`, `GET /conversations`, `GET /conversations/:id`, `GET /download/:filename`. All routes require Clerk auth.
- `agent_claude.py` — Agent orchestration: `run_agent_turn()` (blocking) and `run_agent_turn_streaming()` (generator yielding SSE events). Uses Claude's streaming API.
- `agent_tools.py` (~1050 lines) — All 26 tool definitions and implementations
- `norman_frontend/` — React app (Vite). Main component: `ChatLayout.jsx`. Auth gate in `App.jsx`.

### Agent Tool System (agent_tools.py)

The file contains several subsystems bundled together:

- **QueryExecutor** — Read-only SQL execution against DM03 (operations) or DM01 (harvest planning). Validates queries are SELECT/WITH only, blocks forbidden keywords, limits to 5000 rows.
- **ContextLoader** — Loads YAML-based schema docs from `data-catalog/` for table lookups and full-text search.
- **LearningManager** — Persists successful query patterns, user corrections, and data discoveries to YAML files in `agent-learning/`.
- **ExcelExporter** — Generates `.xlsx` files into `exports/` directory.
- **HarvestPlannerAPI** — HTTP client for external Harvest Planner REST API with JWT auth and token refresh.

### Key Data Flow

1. User sends message via React chat UI → `POST /chat/stream` (SSE)
2. `web_app.py` loads/creates conversation from MongoDB, appends user message
3. `run_agent_turn_streaming()` streams tokens + tool events to frontend via SSE
4. Claude responds with tool calls; agent loop executes tools and feeds results back
5. Final text response committed to React state, rendered as markdown with Chart.js
6. Conversation persisted to MongoDB after streaming completes

### Auth Flow

- Frontend: `@clerk/react` provides `<SignIn>` and session token via `useAuth().getToken()`
- `api.js` attaches Bearer token to all API requests
- Backend: `auth.py` decorator `@require_auth` verifies JWT via Clerk JWKS, sets `request.clerk_user_id`

### Chat Persistence (chat_store.py)

- MongoDB Atlas stores conversations with full Anthropic message format
- `_clean_block()` strips Pydantic-only fields from Anthropic SDK objects before storage (critical — API rejects extra fields like `citations`, `parsed_output`)
- `get_display_messages()` returns only user/assistant text messages for sidebar display

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

## Living Documents

Living documents are shared, daily-cached reports that all users see the same version of (e.g., production plans, pick plans). They are globally consistent — not per-user.

**MongoDB collections:** `living_documents` (definitions) and `living_document_snapshots` (daily snapshots, keyed by `{ doc_id, date }`).

**Module:** `living_docs.py` — CRUD for definitions and snapshots. Uses `_get_db()` from `chat_store.py`.

**Backend routes (`web_app.py`):**
- `GET /living-docs` — list all document definitions
- `POST /living-docs` — create a new document (`name`, `prompt`, `description`)
- `GET /living-docs/<id>` — get definition + latest snapshot (`snapshot` may be null)
- `POST /living-docs/<id>/refresh` — stream-generate today's snapshot via SSE (same protocol as `/chat/stream`)
- `GET /living-docs/<id>/history` — list past snapshot dates (no content)

**Agent tools (`agent_tools.py`):** `list_living_documents`, `get_living_document(name)`, `create_living_document(name, description, prompt)`. The agent creates docs when users type `/living-doc-add`.

**Snapshot generation:** Runs `run_agent_turn_streaming()` with the document's stored prompt. One snapshot per day per document (upsert by `doc_id + date`). Snapshots are never scoped to a user.

**Frontend:** Sidebar shows a "Living Documents" section above conversations. Clicking a doc loads it into a read-only view mode. The topbar shows a ↻ refresh button and the snapshot date. The input area is replaced by a "Return to chat" footer. After every agent turn, the sidebar living-docs list is refreshed to pick up any newly created docs.

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
- Conversations are persisted in MongoDB Atlas (collection: `conversations` in `cobbleai` database).
- The `.env` file contains API keys, database credentials, Clerk keys, and MongoDB URI — never commit it.
- Chart rendering uses a custom `marked` renderer that converts ````chart` fenced blocks into placeholder divs, then `renderCharts()` replaces them with Chart.js canvases.
- Deployment: Cloudflare tunnel proxies `ai.cobblestonecloud.com` → Vite dev server (port 5000), which proxies `/api` to Gunicorn (port 8000). Only the frontend port needs tunnel exposure.
