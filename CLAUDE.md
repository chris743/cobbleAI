# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CobbleAI is a Python-based AI data warehouse agent for a citrus packing operation. It provides a web chat interface for querying the DM03/DM01 data warehouses and managing harvest planning data via a REST API.

## Repository Structure

```
cobbleai/
├── app/                          # App server (Flask + React)
│   ├── web_app.py                # Flask API server (port 8000)
│   ├── agent_claude.py           # Agent orchestration (MCP client)
│   ├── agent_system_prompt.md    # System prompt for Claude
│   ├── auth.py                   # Clerk JWT verification
│   ├── chat_store.py             # MongoDB conversation persistence
│   ├── frontend/                 # React (Vite) app
│   └── requirements.txt
│
├── mcp/                          # MCP tool server (compute)
│   ├── server.py                 # Low-level MCP server (SSE on port 9000)
│   ├── tools/                    # All 36 agent tool implementations
│   ├── living_docs.py            # Living documents CRUD (MongoDB)
│   ├── customer_specs.py         # Customer specs CRUD (MongoDB)
│   ├── o365_auth.py              # Microsoft 365 OAuth
│   ├── db.py                     # MongoDB connection helper
│   ├── data-catalog/             # YAML database schema docs
│   ├── agent-learning/           # Learned query patterns (append-only)
│   ├── exports/                  # Generated Excel/PDF files
│   └── requirements.txt
│
├── db/                           # Database utility scripts (not deployed)
├── .github/workflows/            # CI/CD (triggers on app/** or mcp/**)
├── .env                          # Shared config (repo root, never committed)
└── CLAUDE.md
```

## Tech Stack

- **App Server**: Flask 3.1 (Python 3), served via Gunicorn (`--timeout 300 --workers 3`) on port 8000
- **MCP Server**: Low-level `mcp.server.lowlevel.Server` + Starlette/Uvicorn on port 9000
- **AI**: Anthropic Claude API (`anthropic` SDK) with agentic tool-calling loop, streaming via SSE
- **Database**: Microsoft SQL Server via pyodbc (ODBC Driver 17)
- **Persistence**: MongoDB Atlas for conversations, living docs, customer specs, O365 tokens
- **Auth**: Clerk — React frontend (`@clerk/react`), backend JWT/JWKS verification (`app/auth.py`)
- **Frontend**: React (Vite) on port 5000 with marked.js (markdown) and Chart.js (visualization)
- **Config**: `.env` file at repo root loaded via python-dotenv

## Running the App

```bash
# MCP Server (must start first — tools live here)
cd mcp
pip install -r requirements.txt
python server.py                     # http://127.0.0.1:9000/sse

# App Server
cd app
pip install -r requirements.txt
python web_app.py                    # Dev: http://localhost:8000
# Production: gunicorn web_app:app -b 0.0.0.0:8000 --timeout 300 --workers 3

# Frontend
cd app/frontend
npm install
npm run dev                          # Dev: http://localhost:5000 (proxies API to :8000)
npm run build                        # Production build
npm run lint                         # ESLint

# Agent CLI (bypasses web/auth — useful for debugging tools directly)
cd app
python agent_claude.py "How many bins of Fancy Navels are in inventory?"
python agent_claude.py               # interactive REPL

# DB connectivity check
python db/db_test.py
```

There are no automated tests or CI pipeline configured.

## Required .env Variables

```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-20250514   # optional override
MAX_AGENT_TURNS=10                          # optional override
MCP_URL=http://127.0.0.1:9000/sse          # optional override
MCP_PORT=9000                               # optional override
DB_SERVER=RDGW-CF
DB_DATABASE=DM03
DB_USERNAME=
DB_PASSWORD=
DB_TRUSTED_CONNECTION=yes
QUERY_TIMEOUT=30
MAX_ROWS=5000
CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
MONGO_URI=
MONGO_DB=cobbleai
O365_CLIENT_ID=                             # optional Microsoft 365
O365_CLIENT_SECRET=
O365_TENANT_ID=
O365_REDIRECT_URI=http://localhost:5000/o365/callback
```

## Architecture

### Two-Server Design

The app is split into two independently deployable services:

1. **App Server** (`app/web_app.py`) — Handles HTTP/SSE for the frontend, auth, conversation persistence. Connects to MCP server for tool execution.
2. **MCP Server** (`mcp/server.py`) — Handles all tool execution: SQL queries, data catalog lookups, Excel/PDF exports, O365 integration, living docs. Runs on the machine with database access.

Communication: `agent_claude.py` uses the `mcp` Python SDK's SSE client to call tools on the MCP server. Tool definitions are fetched once and cached.

### Key Data Flow

1. User sends message via React chat UI → `POST /chat/stream` (SSE)
2. `app/web_app.py` loads/creates conversation from MongoDB, appends user message
3. `app/agent_claude.py` → `run_agent_turn_streaming()` streams tokens + tool events
4. Tool calls go to MCP server via SSE → `mcp/server.py` dispatches to `mcp/tools/`
5. Results stream back, rendered as markdown with Chart.js
6. Conversation persisted to MongoDB after streaming completes

### Agent Tool System (mcp/tools/)

36 tools organized as Python modules:

- **QueryExecutor** — Read-only SQL execution against DM03/DM01. Validates SELECT/WITH only, blocks forbidden keywords, limits to 5000 rows.
- **ContextLoader** — Loads YAML-based schema docs from `mcp/data-catalog/`
- **LearningManager** — Persists successful query patterns to `mcp/agent-learning/`
- **ExcelExporter / PDFExporter** — Generates files into `mcp/exports/`
- **HarvestPlannerAPI** — HTTP client for external Harvest Planner REST API
- **Living Documents** — Agent-side CRUD for living document snapshots
- **O365 Tools** — Email, calendar, OneDrive, SharePoint (requires user OAuth)

### Auth Flow

- Frontend: `@clerk/react` provides `<SignIn>` and session token via `useAuth().getToken()`
- `app/frontend/src/lib/api.js` attaches Bearer token to all API requests
- Backend: `app/auth.py` decorator `@require_auth` verifies JWT via Clerk JWKS, sets `request.clerk_user_id`

### Chat Persistence (app/chat_store.py)

- MongoDB Atlas stores conversations with full Anthropic message format
- `_clean_block()` strips Pydantic-only fields from Anthropic SDK objects before storage (critical — API rejects extra fields like `citations`, `parsed_output`)

### Cross-Package Imports

`app/web_app.py` adds `mcp/` to `sys.path` to directly import `living_docs`, `customer_specs`, and `o365_auth` for Flask routes that don't go through the agent (CRUD endpoints). These share MongoDB via `mcp/db.py`.

## Living Documents

Shared, daily-cached reports consistent across all users. MongoDB collections: `living_documents` (definitions) and `living_document_snapshots` (daily snapshots, keyed by `{ doc_id, date }`).

Module: `mcp/living_docs.py`. Agent tools in `mcp/tools/living_documents.py`. Frontend: sidebar section above conversations, read-only view mode with refresh button.

## Key Business Concepts

- **Bin**: Bulk container (~23.2 cartons for most commodities, 37.5 for mandarins)
- **Carton**: Standard shipping unit (40 lbs, except mandarins at 25 lbs)
- **Style**: Packaging format that determines equipment line (FB, CB, NB, WM, HD, Bulk)
- **Size**: Always 3-digit zero-padded strings (e.g., `'088'`)
- **Source systems**: Cobblestone (CF) for grower accounting, LP for inventory/packing/sales

## Important Conventions

- SQL queries must be read-only (SELECT/WITH). Forbidden keywords validated in `QueryExecutor`.
- Agent learning files (`mcp/agent-learning/*.yaml`) are append-only during runtime.
- Excel/PDF exports go to `mcp/exports/` with UUID-based filenames.
- The `.env` file at repo root contains all secrets — never commit it.
- Chart rendering uses a custom `marked` renderer that converts ````chart` fenced blocks into Chart.js canvases.
- Deployment: Cloudflare tunnel proxies `ai.cobblestonecloud.com` → Vite dev server (port 5000), which proxies `/api` to Gunicorn (port 8000).
