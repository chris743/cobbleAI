"""
Query Executor for DM03 Data Warehouse
This is the "API" that AI agents use to query your data.

Usage:
    from query_executor import QueryExecutor
    
    executor = QueryExecutor()
    result = executor.execute("SELECT TOP 10 * FROM dbo.VW_BININVENTORY")
"""

import pyodbc
import json
import re
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

# Connection settings
SERVER = 'RDGW-CF'
DATABASE = 'DM03'
CONNECTION_STRING = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;'


class QueryExecutor:
    """
    Minimal, safe SQL executor for AI agent access.
    Read-only by design.
    """
    
    # Forbidden keywords - queries containing these will be rejected
    FORBIDDEN_PATTERNS = [
        r'\bINSERT\b',
        r'\bUPDATE\b', 
        r'\bDELETE\b',
        r'\bDROP\b',
        r'\bTRUNCATE\b',
        r'\bALTER\b',
        r'\bCREATE\b',
        r'\bEXEC\b',
        r'\bEXECUTE\b',
        r'\bGRANT\b',
        r'\bREVOKE\b',
        r'\bINTO\b',  # SELECT INTO
        r'--',        # SQL comments (potential injection)
        r'/\*',       # Block comments
        r'xp_',       # Extended stored procedures
        r'sp_',       # System stored procedures
    ]
    
    # Maximum rows to return (prevents memory issues)
    MAX_ROWS = 5000
    
    # Query timeout in seconds
    TIMEOUT = 30
    
    def __init__(self, connection_string: str = CONNECTION_STRING):
        self.connection_string = connection_string
    
    def _validate_query(self, sql: str) -> tuple[bool, str]:
        """
        Validate that a query is safe to execute.
        Returns (is_valid, error_message).
        """
        sql_upper = sql.upper().strip()
        
        # Must start with SELECT or WITH (for CTEs)
        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            return False, "Query must start with SELECT or WITH"
        
        # Check for forbidden patterns
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, sql, re.IGNORECASE):
                return False, f"Query contains forbidden pattern: {pattern}"
        
        return True, ""
    
    def _serialize_value(self, val):
        """Convert SQL values to JSON-serializable types."""
        if val is None:
            return None
        elif isinstance(val, (datetime, date)):
            return val.isoformat()
        elif isinstance(val, Decimal):
            return float(val)
        elif isinstance(val, bytes):
            return val.hex()
        else:
            return val
    
    def execute(self, sql: str, max_rows: Optional[int] = None) -> dict:
        """
        Execute a SQL query and return results.
        
        Args:
            sql: The SELECT query to execute
            max_rows: Maximum rows to return (default: MAX_ROWS)
            
        Returns:
            dict with keys:
                - success: bool
                - columns: list of column names (if success)
                - rows: list of row data (if success)
                - row_count: number of rows returned
                - truncated: whether results were truncated
                - error: error message (if not success)
                - query: the executed query
        """
        max_rows = min(max_rows or self.MAX_ROWS, self.MAX_ROWS)
        
        # Validate query
        is_valid, error_msg = self._validate_query(sql)
        if not is_valid:
            return {
                'success': False,
                'error': error_msg,
                'query': sql
            }
        
        try:
            conn = pyodbc.connect(self.connection_string, timeout=self.TIMEOUT)
            cursor = conn.cursor()
            
            # Execute with timeout
            cursor.execute(sql)
            
            # Get column names
            columns = [desc[0] for desc in cursor.description]
            
            # Fetch rows (one extra to detect truncation)
            rows = cursor.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            
            # Serialize values
            serialized_rows = [
                [self._serialize_value(val) for val in row]
                for row in rows
            ]
            
            conn.close()
            
            return {
                'success': True,
                'columns': columns,
                'rows': serialized_rows,
                'row_count': len(serialized_rows),
                'truncated': truncated,
                'query': sql
            }
            
        except pyodbc.Error as e:
            return {
                'success': False,
                'error': f"Database error: {str(e)}",
                'query': sql
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error: {str(e)}",
                'query': sql
            }
    
    def list_views(self) -> dict:
        """List all available views."""
        sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME 
            FROM INFORMATION_SCHEMA.VIEWS 
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        return self.execute(sql)
    
    def describe_view(self, schema: str, view_name: str) -> dict:
        """Get column information for a view."""
        sql = f"""
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}' 
              AND TABLE_NAME = '{view_name}'
            ORDER BY ORDINAL_POSITION
        """
        return self.execute(sql)
    
    def sample_view(self, full_view_name: str, n: int = 5) -> dict:
        """Get sample rows from a view."""
        n = min(n, 100)  # Cap at 100 for samples
        sql = f"SELECT TOP {n} * FROM {full_view_name}"
        return self.execute(sql)


# =============================================================================
# Agent Tools - These are the functions your AI agent will call
# =============================================================================

def get_tools():
    """
    Returns tool definitions in a format suitable for LLM function calling.
    Use this when setting up your agent.
    """
    return [
        {
            "name": "execute_sql",
            "description": "Execute a read-only SQL query against the data warehouse. Only SELECT queries are allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL SELECT query to execute"
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Maximum number of rows to return (default 1000, max 5000)"
                    }
                },
                "required": ["sql"]
            }
        },
        {
            "name": "list_available_views",
            "description": "List all available views in the data warehouse",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "describe_view",
            "description": "Get column information for a specific view",
            "parameters": {
                "type": "object", 
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": "The schema name (e.g., 'dbo', 'rpt', 'Ref')"
                    },
                    "view_name": {
                        "type": "string",
                        "description": "The view name without schema prefix"
                    }
                },
                "required": ["schema", "view_name"]
            }
        },
        {
            "name": "sample_view",
            "description": "Get sample rows from a view to understand its data",
            "parameters": {
                "type": "object",
                "properties": {
                    "full_view_name": {
                        "type": "string",
                        "description": "Full view name including schema (e.g., 'dbo.VW_BININVENTORY')"
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of sample rows (default 5, max 100)"
                    }
                },
                "required": ["full_view_name"]
            }
        }
    ]


def handle_tool_call(tool_name: str, parameters: dict) -> dict:
    """
    Handle a tool call from an AI agent.
    
    Usage:
        result = handle_tool_call("execute_sql", {"sql": "SELECT TOP 10 * FROM dbo.VW_BININVENTORY"})
    """
    executor = QueryExecutor()
    
    if tool_name == "execute_sql":
        return executor.execute(
            parameters.get("sql", ""),
            parameters.get("max_rows")
        )
    elif tool_name == "list_available_views":
        return executor.list_views()
    elif tool_name == "describe_view":
        return executor.describe_view(
            parameters.get("schema", "dbo"),
            parameters.get("view_name", "")
        )
    elif tool_name == "sample_view":
        return executor.sample_view(
            parameters.get("full_view_name", ""),
            parameters.get("n", 5)
        )
    else:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == '__main__':
    import sys
    
    executor = QueryExecutor()
    
    if len(sys.argv) > 1:
        # Run query from command line
        sql = ' '.join(sys.argv[1:])
        result = executor.execute(sql)
    else:
        # Interactive mode
        print("DM03 Query Executor - Interactive Mode")
        print("Type SQL queries or 'exit' to quit\n")
        
        while True:
            try:
                sql = input("SQL> ").strip()
                if sql.lower() == 'exit':
                    break
                if not sql:
                    continue
                    
                result = executor.execute(sql)
                print(json.dumps(result, indent=2, default=str))
                print()
                
            except KeyboardInterrupt:
                break
    
    print("\nDone.")