# MCP Service Deployment Guide

## Prerequisites

| Requirement | Details |
|---|---|
| Python | 3.9+ |
| ODBC Driver 17 | For SQL Server connectivity |
| Network access | SQL Server (RDGW-CF), MongoDB Atlas |
| Port 9000 | Available for SSE transport |
| Writable dirs | `mcp/exports/`, `mcp/agent-learning/` |

## 1. Clone & Setup

```bash
git clone <repo-url> /opt/cobbleai
cd /opt/cobbleai/mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Install ODBC Driver 17

**Ubuntu/Debian:**

```bash
curl https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc
sudo add-apt-repository "$(curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list)"
sudo apt update && sudo apt install -y msodbcsql17 unixodbc-dev
```

**Windows:** Download and run the installer from Microsoft.

## 3. Environment Variables

Create `.env` at the repo root (`/opt/cobbleai/.env`):

```env
# Required — SQL Server
DB_SERVER=RDGW-CF
DB_DATABASE=DM03
DB_USERNAME=
DB_PASSWORD=
DB_TRUSTED_CONNECTION=yes
QUERY_TIMEOUT=30
MAX_ROWS=5000

# Required — MongoDB
MONGO_URI=mongodb+srv://...
MONGO_DB=cobbleai

# Optional — Server config
MCP_PORT=9000

# Optional — Harvest Planner API
HP_BASE_URL=https://api.cobblestonecloud.com
HP_USERNAME=
HP_PASSWORD=

# Optional — Microsoft 365
O365_CLIENT_ID=
O365_CLIENT_SECRET=
O365_TENANT_ID=
O365_REDIRECT_URI=http://localhost:5000/o365/callback

# Optional — Local LLM (vLLM) for large result summarization
LOCAL_LLM_ENABLED=false
LOCAL_LLM_URL=http://127.0.0.1:8100
LOCAL_LLM_MODEL=Qwen/Qwen3-32B
LOCAL_LLM_ROW_THRESHOLD=500
LOCAL_LLM_CHAR_THRESHOLD=50000
LOCAL_LLM_TIMEOUT=90
LOCAL_LLM_MAX_INPUT_ROWS=300
```

## 4. Verify Connectivity

```bash
# Test SQL Server
python -c "import pyodbc; pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=RDGW-CF;DATABASE=DM03;Trusted_Connection=yes')"

# Test MongoDB
python -c "from db import _get_db; print(_get_db().list_collection_names())"
```

## 5. Run

**Dev:**

```bash
cd /opt/cobbleai/mcp
python server.py
# → http://127.0.0.1:9000/sse
```

**Production (systemd):**

Create `/etc/systemd/system/cobbleai-mcp.service`:

```ini
[Unit]
Description=CobbleAI MCP Server
After=network.target

[Service]
Type=simple
User=cobbleai
WorkingDirectory=/opt/cobbleai/mcp
Environment=PATH=/opt/cobbleai/mcp/.venv/bin:/usr/bin
ExecStart=/opt/cobbleai/mcp/.venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cobbleai-mcp
sudo systemctl status cobbleai-mcp
```

## 6. Verify Deployment

```bash
# Health check — SSE endpoint should accept connections
curl -N http://127.0.0.1:9000/sse

# Check logs
journalctl -u cobbleai-mcp -f
```

Startup logs should show:

```
Loaded 36 tool definitions
Local LLM: disabled
Starting MCP server on http://127.0.0.1:9000/sse
```

## 7. Connect the App Server

On the app server, set `MCP_URL` in `.env`:

```env
MCP_URL=http://<mcp-host>:9000/sse
```

If the MCP server runs on the same machine, the default `http://127.0.0.1:9000/sse` works.

## Important Notes

- **Server binds to `127.0.0.1`** by default — if the app server is on a different machine, you'll need to either change the bind address in `server.py` or use a reverse proxy/tunnel.
- **No auth on MCP server** — it trusts the app server. Keep it behind a firewall or on a private network.
- **`exports/` directory** accumulates files over time (UUID-named Excel/PDF). Consider a cron job to clean old files.
- **`agent-learning/` is append-only** — YAML files grow as the agent learns query patterns. Back these up.
- **Current CI/CD** (`.github/workflows/deploy-mcp.yml`) is a stub — you'll need to fill in SSH deploy steps for automated deployments.
