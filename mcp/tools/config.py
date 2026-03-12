"""Shared configuration and database connection strings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root (may already be loaded by server.py)
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# Default data paths relative to the mcp/ directory
_MCP_DIR = str(Path(__file__).resolve().parent.parent)

CONFIG = {
    "server": os.getenv("DB_SERVER", "RDGW-CF"),
    "database": os.getenv("DB_DATABASE", "DM03"),
    "username": os.getenv("DB_USERNAME"),
    "password": os.getenv("DB_PASSWORD"),
    "trusted_connection": os.getenv("DB_TRUSTED_CONNECTION", "yes").lower() == "yes",
    "context_path": os.getenv("CONTEXT_PATH", os.path.join(_MCP_DIR, "data-catalog")),
    "learning_path": os.getenv("LEARNING_PATH", os.path.join(_MCP_DIR, "agent-learning")),
    "max_rows": int(os.getenv("MAX_ROWS", "5000")),
    "query_timeout": int(os.getenv("QUERY_TIMEOUT", "30")),
    # Harvest Planner API
    "hp_base_url": os.getenv("HP_BASE_URL", "").rstrip("/"),
    "hp_username": os.getenv("HP_USERNAME", ""),
    "hp_password": os.getenv("HP_PASSWORD", ""),
}


def _build_conn_string(database: str) -> str:
    if CONFIG["trusted_connection"]:
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={CONFIG['server']};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    return (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={CONFIG['server']};"
        f"DATABASE={database};"
        f"UID={CONFIG['username']};"
        f"PWD={CONFIG['password']};"
        f"Encrypt=no;"
        f"TrustServerCertificate=yes;"
        f"Application Name=DM03_Agent;"
    )


CONNECTION_STRINGS = {
    "DM03": _build_conn_string("DM03"),
    "DM01": _build_conn_string("DM01"),
}
CONNECTION_STRING = CONNECTION_STRINGS["DM03"]
