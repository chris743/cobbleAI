"""Safe, read-only SQL executor for agent queries."""

import pyodbc
from datetime import datetime
from typing import Optional, Any
from decimal import Decimal

from .config import CONFIG, CONNECTION_STRING, CONNECTION_STRINGS


class QueryExecutor:
    """Safe, read-only SQL executor for agent queries."""

    FORBIDDEN_PATTERNS = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 'ALTER', 'CREATE',
        'EXEC', 'EXECUTE', 'GRANT', 'REVOKE', 'INTO', '--', '/*', 'xp_', 'sp_'
    ]

    def __init__(self, connection_string: str = CONNECTION_STRING):
        self.connection_string = connection_string
        self.max_rows = CONFIG["max_rows"]
        self.timeout = CONFIG["query_timeout"]

    def _validate_query(self, sql: str) -> tuple[bool, str]:
        sql_upper = sql.upper().strip()

        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            return False, "Query must start with SELECT or WITH"

        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in sql_upper:
                return False, f"Query contains forbidden keyword: {pattern}"

        return True, ""

    def _serialize(self, val: Any) -> Any:
        if val is None:
            return None
        elif isinstance(val, datetime):
            return val.isoformat()
        elif isinstance(val, Decimal):
            return float(val)
        elif isinstance(val, bytes):
            return val.hex()
        return val

    def execute(self, sql: str, max_rows: Optional[int] = None, database: str = None,
                _internal_limit: int = None) -> dict:
        effective_max = _internal_limit or self.max_rows
        max_rows = min(max_rows or effective_max, effective_max)

        is_valid, error = self._validate_query(sql)
        if not is_valid:
            return {"success": False, "error": error, "sql": sql}

        conn_str = self.connection_string
        if database and database.upper() in CONNECTION_STRINGS:
            conn_str = CONNECTION_STRINGS[database.upper()]

        try:
            conn = pyodbc.connect(conn_str, timeout=self.timeout)
            cursor = conn.cursor()
            cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]

            serialized = [[self._serialize(v) for v in row] for row in rows]
            conn.close()

            return {
                "success": True,
                "columns": columns,
                "rows": serialized,
                "row_count": len(serialized),
                "truncated": truncated,
                "sql": sql
            }
        except Exception as e:
            return {"success": False, "error": str(e), "sql": sql}


TOOL_DEFINITIONS = [
    {
        "name": "execute_sql",
        "description": "Execute a read-only SQL query against a data warehouse. Only SELECT queries are allowed. Returns columns, rows, and row count. Defaults to DM03. Use database='DM01' for harvest planning data (dbo.harvestplanentry, dbo.harvestcontractors, dbo.processproductionruns).",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL SELECT query to execute"
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 1000, max 5000)"
                },
                "database": {
                    "type": "string",
                    "enum": ["DM03", "DM01"],
                    "description": "Target database. DM03 (default) for inventory/sales/operations. DM01 for harvest planning data."
                }
            },
            "required": ["sql"]
        }
    },
]


def register_handlers(executor: QueryExecutor) -> dict:
    return {
        "execute_sql": lambda p: executor.execute(
            p.get("sql", ""), p.get("max_rows"), p.get("database")
        ),
    }
