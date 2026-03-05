"""
DM03 Data Warehouse Agent Tools
================================
Tool framework for AI agents to query and learn from the data warehouse.

Components:
1. Query Executor - Run validated SQL against the warehouse
2. Context Loader - Load schema documentation into agent context
3. Learning Tools - Record discoveries, corrections, and successful patterns

Usage:
    from agent_tools import AgentToolkit
    
    toolkit = AgentToolkit()
    
    # Get tools for LLM function calling
    tools = toolkit.get_tool_definitions()
    
    # Handle a tool call from the agent
    result = toolkit.handle_tool_call("execute_sql", {"sql": "SELECT ..."})
"""

import pyodbc
import yaml
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from decimal import Decimal
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# CONFIGURATION (from .env)
# =============================================================================

CONFIG = {
    "server": os.getenv("DB_SERVER", "RDGW-CF"),
    "database": os.getenv("DB_DATABASE", "DM03"),
    "username": os.getenv("DB_USERNAME"),
    "password": os.getenv("DB_PASSWORD"),
    "trusted_connection": os.getenv("DB_TRUSTED_CONNECTION", "yes").lower() == "yes",
    "context_path": os.getenv("CONTEXT_PATH", "./data-catalog"),
    "learning_path": os.getenv("LEARNING_PATH", "./agent-learning"),
    "max_rows": int(os.getenv("MAX_ROWS", "5000")),
    "query_timeout": int(os.getenv("QUERY_TIMEOUT", "30")),
}

# Build connection string
if CONFIG["trusted_connection"]:
    CONNECTION_STRING = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={CONFIG['server']};"
        f"DATABASE={CONFIG['database']};"
        f"Trusted_Connection=yes;"
    )
else:
    CONNECTION_STRING = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={CONFIG['server']};"
        f"DATABASE={CONFIG['database']};"
        f"UID={CONFIG['username']};"
        f"PWD={CONFIG['password']};"
        f"Encrypt=no;"
        f"TrustServerCertificate=yes;"
        f"Application Name=DM03_Agent;"
    )


# =============================================================================
# QUERY EXECUTOR
# =============================================================================

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
    
    def execute(self, sql: str, max_rows: Optional[int] = None) -> dict:
        max_rows = min(max_rows or self.max_rows, self.max_rows)
        
        is_valid, error = self._validate_query(sql)
        if not is_valid:
            return {"success": False, "error": error, "sql": sql}
        
        try:
            conn = pyodbc.connect(self.connection_string, timeout=self.timeout)
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


# =============================================================================
# CONTEXT LOADER
# =============================================================================

class ContextLoader:
    """Load and search schema documentation."""
    
    def __init__(self, context_path: str = CONFIG["context_path"]):
        self.context_path = Path(context_path)
    
    def load_file(self, filename: str) -> dict:
        """Load a specific YAML file from context."""
        filepath = self.context_path / filename
        if not filepath.exists():
            return {"error": f"File not found: {filename}"}
        
        with open(filepath, 'r') as f:
            return yaml.safe_load(f)
    
    def load_system_architecture(self) -> dict:
        """Load the system architecture reference."""
        return self.load_file("system_architecture.yaml")
    
    def load_glossary(self) -> dict:
        """Load the business glossary."""
        return self.load_file("glossary.yaml")

    def load_size_dictionary(self, commodity: str = None) -> dict:
        """Load size reference data, optionally filtered to one commodity."""
        data = self.load_file("size_dictionary.yaml")
        if "error" in data:
            return data
        if commodity:
            commodity_upper = commodity.upper()
            commodities = data.get("commodities", {})
            for key, val in commodities.items():
                if key.upper() == commodity_upper:
                    return {"commodity": key, **val, "special_size_codes": data.get("special_size_codes", {})}
            return {"error": f"Commodity not found: {commodity}. Available: {list(commodities.keys())}"}
        return data
    
    def load_domain(self, domain_name: str) -> dict:
        """Load a domain definition."""
        return self.load_file(f"domains/{domain_name}/_domain.yaml")
    
    def load_table_schema(self, table_name: str) -> dict:
        """Load schema documentation for a specific table."""
        # Normalize the table name for searching
        search_name = table_name.lower()
        search_name = search_name.replace("dbo.", "").replace("rpt.", "").replace("ref.", "")
        search_name = search_name.replace("vw_", "").replace("_", "")
        
        # Try to find the table file
        for yaml_file in self.context_path.rglob("*.yaml"):
            file_stem = yaml_file.stem.lower().replace("vw_", "").replace("_", "")
            
            # Check if this file matches
            if search_name in file_stem or file_stem in search_name:
                with open(yaml_file, 'r') as f:
                    content = yaml.safe_load(f)
                    # Verify it's actually a table schema
                    if isinstance(content, dict) and "columns" in content:
                        return content
        
        # Also try exact name match on the 'name' field inside files
        for yaml_file in self.context_path.rglob("*.yaml"):
            try:
                with open(yaml_file, 'r') as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        doc_name = content.get("name", "").lower()
                        if table_name.lower() in doc_name or doc_name in table_name.lower():
                            if "columns" in content:
                                return content
            except:
                pass
        
        return {"error": f"Schema not found for table: {table_name}"}
    
    def list_tables(self) -> list[str]:
        """List all documented tables."""
        tables = []
        for yaml_file in self.context_path.rglob("*.yaml"):
            content = self.load_file(str(yaml_file.relative_to(self.context_path)))
            if isinstance(content, dict) and content.get("name", "").startswith("dbo."):
                tables.append(content["name"])
        return tables
    
    def search_context(self, query: str) -> list[dict]:
        """Search across all documentation for relevant info."""
        results = []
        query_lower = query.lower()
        
        for yaml_file in self.context_path.rglob("*.yaml"):
            try:
                with open(yaml_file, 'r') as f:
                    content = f.read()
                    if query_lower in content.lower():
                        results.append({
                            "file": str(yaml_file.relative_to(self.context_path)),
                            "preview": content[:500] + "..." if len(content) > 500 else content
                        })
            except:
                pass
        
        return results
    
    def get_full_context(self) -> str:
        """Generate complete context document for agent."""
        context_parts = []
        
        # System architecture first
        arch = self.load_system_architecture()
        if "error" not in arch:
            context_parts.append("# SYSTEM ARCHITECTURE\n" + yaml.dump(arch))
        
        # Glossary
        glossary = self.load_glossary()
        if "error" not in glossary:
            context_parts.append("# GLOSSARY\n" + yaml.dump(glossary))
        
        # All table schemas
        for yaml_file in self.context_path.rglob("*.yaml"):
            if yaml_file.name.startswith("vw_") or yaml_file.name.startswith("bininv"):
                with open(yaml_file, 'r') as f:
                    context_parts.append(f"# TABLE: {yaml_file.stem}\n" + f.read())
        
        return "\n\n---\n\n".join(context_parts)


# =============================================================================
# LEARNING TOOLS
# =============================================================================

class LearningManager:
    """Manage agent learning - queries, corrections, discoveries."""
    
    def __init__(self, learning_path: str = CONFIG["learning_path"]):
        self.learning_path = Path(learning_path)
        self.learning_path.mkdir(exist_ok=True)
        
        self.queries_file = self.learning_path / "learned_queries.yaml"
        self.corrections_file = self.learning_path / "corrections.yaml"
        self.discoveries_file = self.learning_path / "discoveries.yaml"
        
        # Initialize files if they don't exist
        for f in [self.queries_file, self.corrections_file, self.discoveries_file]:
            if not f.exists():
                with open(f, 'w') as file:
                    yaml.dump({"entries": []}, file)
    
    def _load_file(self, filepath: Path) -> dict:
        with open(filepath, 'r') as f:
            return yaml.safe_load(f) or {"entries": []}
    
    def _save_file(self, filepath: Path, data: dict):
        with open(filepath, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    def remember_query(self, question: str, sql: str, notes: str = "") -> dict:
        """Store a successful query pattern for future reference."""
        data = self._load_file(self.queries_file)
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "sql": sql,
            "notes": notes,
            "verified": False
        }
        
        data["entries"].append(entry)
        self._save_file(self.queries_file, data)
        
        return {"success": True, "message": "Query pattern saved"}
    
    def log_correction(self, table: str, column: str, 
                       wrong_assumption: str, correct_meaning: str) -> dict:
        """Log when the agent was corrected about something."""
        data = self._load_file(self.corrections_file)
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "table": table,
            "column": column,
            "wrong_assumption": wrong_assumption,
            "correct_meaning": correct_meaning,
            "applied_to_docs": False
        }
        
        data["entries"].append(entry)
        self._save_file(self.corrections_file, data)
        
        return {"success": True, "message": "Correction logged"}
    
    def record_discovery(self, category: str, key: str, value: str) -> dict:
        """Record a new discovery about the data or schema."""
        data = self._load_file(self.discoveries_file)
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "category": category,  # column_meaning, join_pattern, gotcha, business_rule
            "key": key,
            "value": value,
            "verified": False
        }
        
        data["entries"].append(entry)
        self._save_file(self.discoveries_file, data)
        
        return {"success": True, "message": "Discovery recorded"}
    
    def get_learned_queries(self, search: str = None) -> list[dict]:
        """Retrieve learned query patterns, optionally filtered."""
        data = self._load_file(self.queries_file)
        entries = data.get("entries", [])
        
        if search:
            search_lower = search.lower()
            entries = [e for e in entries 
                      if search_lower in e.get("question", "").lower() 
                      or search_lower in e.get("sql", "").lower()]
        
        return entries
    
    def get_corrections(self) -> list[dict]:
        """Get all logged corrections."""
        data = self._load_file(self.corrections_file)
        return data.get("entries", [])
    
    def get_discoveries(self, category: str = None) -> list[dict]:
        """Get recorded discoveries, optionally by category."""
        data = self._load_file(self.discoveries_file)
        entries = data.get("entries", [])
        
        if category:
            entries = [e for e in entries if e.get("category") == category]
        
        return entries


# =============================================================================
# AGENT TOOLKIT - Main Interface
# =============================================================================

class AgentToolkit:
    """
    Main interface for AI agent tools.
    Combines query execution, context loading, and learning.
    """
    
    def __init__(self):
        self.executor = QueryExecutor()
        self.context = ContextLoader()
        self.learning = LearningManager()
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for LLM function calling."""
        return [
            # === QUERY TOOLS ===
            {
                "name": "execute_sql",
                "description": "Execute a read-only SQL query against the DM03 data warehouse. Only SELECT queries are allowed. Returns columns, rows, and row count.",
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
                        }
                    },
                    "required": ["sql"]
                }
            },
            
            # === CONTEXT TOOLS ===
            {
                "name": "get_system_architecture",
                "description": "Load the system architecture document. Contains critical info about CF/LP systems, join rules, and column naming conventions. READ THIS FIRST before writing queries.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_glossary",
                "description": "Load the business glossary with definitions for domain terms like Bin, Carton, Pool, Grower, Packout, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_table_schema",
                "description": "Load detailed schema documentation for a specific table including column descriptions, relationships, and sample queries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "Table name (e.g., 'VW_BININVENTORY', 'BININVSNAPSHOTS_EXT')"
                        }
                    },
                    "required": ["table_name"]
                }
            },
            {
                "name": "search_context",
                "description": "Search across all documentation for a term or concept.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term to find in documentation"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "list_available_tables",
                "description": "List all documented tables in the data warehouse.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_size_dictionary",
                "description": "Get valid fruit sizes by commodity from local reference data. Use this INSTEAD of querying the database when the user asks about sizes, size lists, or size ranges for a commodity. Returns all valid size codes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "commodity": {
                            "type": "string",
                            "description": "Optional commodity name (e.g., 'NAVEL', 'MANDARIN'). Omit to get all commodities."
                        }
                    }
                }
            },

            # === LEARNING TOOLS ===
            {
                "name": "remember_query",
                "description": "Save a successful query pattern for future reference. Call this when a query works well so you can reuse the pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The natural language question this query answers"
                        },
                        "sql": {
                            "type": "string",
                            "description": "The SQL query that worked"
                        },
                        "notes": {
                            "type": "string",
                            "description": "Any notes about why this works or gotchas"
                        }
                    },
                    "required": ["question", "sql"]
                }
            },
            {
                "name": "log_correction",
                "description": "Log when you were corrected about something. This helps improve documentation over time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "description": "Table the correction applies to"
                        },
                        "column": {
                            "type": "string",
                            "description": "Column name if applicable"
                        },
                        "wrong_assumption": {
                            "type": "string",
                            "description": "What you incorrectly assumed"
                        },
                        "correct_meaning": {
                            "type": "string",
                            "description": "The correct interpretation"
                        }
                    },
                    "required": ["table", "wrong_assumption", "correct_meaning"]
                }
            },
            {
                "name": "record_discovery",
                "description": "Record a new discovery about the data, schema, or business rules.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["column_meaning", "join_pattern", "gotcha", "business_rule"],
                            "description": "Category of discovery"
                        },
                        "key": {
                            "type": "string",
                            "description": "Short identifier (e.g., column name, table name)"
                        },
                        "value": {
                            "type": "string",
                            "description": "What you discovered"
                        }
                    },
                    "required": ["category", "key", "value"]
                }
            },
            {
                "name": "get_learned_queries",
                "description": "Retrieve previously successful query patterns. Check this before writing a new query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "Optional search term to filter queries"
                        }
                    }
                }
            },
            {
                "name": "get_discoveries",
                "description": "Retrieve recorded discoveries about the data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["column_meaning", "join_pattern", "gotcha", "business_rule"],
                            "description": "Filter by category"
                        }
                    }
                }
            }
        ]
    
    def handle_tool_call(self, tool_name: str, parameters: dict) -> dict:
        """Route a tool call to the appropriate handler."""
        
        handlers = {
            # Query tools
            "execute_sql": lambda p: self.executor.execute(
                p.get("sql", ""), p.get("max_rows")
            ),
            
            # Context tools
            "get_system_architecture": lambda p: self.context.load_system_architecture(),
            "get_glossary": lambda p: self.context.load_glossary(),
            "get_size_dictionary": lambda p: self.context.load_size_dictionary(p.get("commodity")),
            "get_table_schema": lambda p: self.context.load_table_schema(p.get("table_name", "")),
            "search_context": lambda p: self.context.search_context(p.get("query", "")),
            "list_available_tables": lambda p: self.context.list_tables(),
            
            # Learning tools
            "remember_query": lambda p: self.learning.remember_query(
                p.get("question", ""), p.get("sql", ""), p.get("notes", "")
            ),
            "log_correction": lambda p: self.learning.log_correction(
                p.get("table", ""), p.get("column", ""),
                p.get("wrong_assumption", ""), p.get("correct_meaning", "")
            ),
            "record_discovery": lambda p: self.learning.record_discovery(
                p.get("category", ""), p.get("key", ""), p.get("value", "")
            ),
            "get_learned_queries": lambda p: self.learning.get_learned_queries(p.get("search")),
            "get_discoveries": lambda p: self.learning.get_discoveries(p.get("category")),
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        
        return handler(parameters)


# =============================================================================
# CLI FOR TESTING
# =============================================================================

if __name__ == "__main__":
    toolkit = AgentToolkit()
    
    print("DM03 Agent Toolkit - Interactive Test Mode")
    print("=" * 50)
    print("\nAvailable tools:")
    for tool in toolkit.get_tool_definitions():
        print(f"  - {tool['name']}: {tool['description'][:60]}...")
    
    print("\n\nTest: Loading system architecture...")
    result = toolkit.handle_tool_call("get_system_architecture", {})
    if "error" not in result:
        print("  ✓ System architecture loaded")
    else:
        print(f"  ✗ Error: {result['error']}")
    
    print("\nTest: Loading glossary...")
    result = toolkit.handle_tool_call("get_glossary", {})
    if "error" not in result:
        print("  ✓ Glossary loaded")
    else:
        print(f"  ✗ Error: {result['error']}")
    
    print("\nTest: Recording a discovery...")
    result = toolkit.handle_tool_call("record_discovery", {
        "category": "gotcha",
        "key": "test_key",
        "value": "This is a test discovery"
    })
    print(f"  {result}")
    
    print("\nToolkit ready for agent integration.")