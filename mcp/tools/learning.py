"""Agent learning — queries, corrections, discoveries."""

import yaml
from datetime import datetime
from pathlib import Path

from .config import CONFIG


class LearningManager:
    """Manage agent learning - queries, corrections, discoveries."""

    def __init__(self, learning_path: str = CONFIG["learning_path"]):
        self.learning_path = Path(learning_path)
        self.learning_path.mkdir(exist_ok=True)

        self.queries_file = self.learning_path / "learned_queries.yaml"
        self.corrections_file = self.learning_path / "corrections.yaml"
        self.discoveries_file = self.learning_path / "discoveries.yaml"

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
        data = self._load_file(self.discoveries_file)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "key": key,
            "value": value,
            "verified": False
        }
        data["entries"].append(entry)
        self._save_file(self.discoveries_file, data)
        return {"success": True, "message": "Discovery recorded"}

    def get_learned_queries(self, search: str = None) -> list[dict]:
        data = self._load_file(self.queries_file)
        entries = data.get("entries", [])
        if search:
            search_lower = search.lower()
            entries = [e for e in entries
                       if search_lower in e.get("question", "").lower()
                       or search_lower in e.get("sql", "").lower()]
        return entries

    def get_corrections(self) -> list[dict]:
        data = self._load_file(self.corrections_file)
        return data.get("entries", [])

    def get_discoveries(self, category: str = None) -> list[dict]:
        data = self._load_file(self.discoveries_file)
        entries = data.get("entries", [])
        if category:
            entries = [e for e in entries if e.get("category") == category]
        return entries


TOOL_DEFINITIONS = [
    {
        "name": "remember_query",
        "description": "Save a successful query pattern for future reference. Call this when a query works well so you can reuse the pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The natural language question this query answers"},
                "sql": {"type": "string", "description": "The SQL query that worked"},
                "notes": {"type": "string", "description": "Any notes about why this works or gotchas"}
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
                "table": {"type": "string", "description": "Table the correction applies to"},
                "column": {"type": "string", "description": "Column name if applicable"},
                "wrong_assumption": {"type": "string", "description": "What you incorrectly assumed"},
                "correct_meaning": {"type": "string", "description": "The correct interpretation"}
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
                "key": {"type": "string", "description": "Short identifier (e.g., column name, table name)"},
                "value": {"type": "string", "description": "What you discovered"}
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
                "search": {"type": "string", "description": "Optional search term to filter queries"}
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
    },
    {
        "name": "save_customer_spec",
        "description": "Save a customer-specific specification or preference. Use when the user tells you about a customer's size requirements, grade tolerances, packaging preferences, DC-specific rules, or any other customer-specific rule. Examples: 'Costco Mira Loma can take 88s', 'Safeway Portland is tougher on grade'.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": "Customer name (e.g., 'Costco', 'Safeway', 'Walmart')"},
                "spec_type": {
                    "type": "string",
                    "enum": ["size", "grade", "packaging", "label", "pallet", "general"],
                    "description": "Type of specification"
                },
                "rule": {"type": "string", "description": "The specific rule or preference in plain language"},
                "dc": {"type": "string", "description": "Distribution center or location if the rule is DC-specific (e.g., 'Mira Loma', 'Sumner', 'Portland')"}
            },
            "required": ["customer", "spec_type", "rule"]
        }
    },
    {
        "name": "get_customer_specs",
        "description": "Retrieve saved customer specifications and preferences. Check this when building production schedules, making size substitution recommendations, or answering questions about what a customer accepts.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": "Optional customer name to filter by"}
            }
        }
    },
]


def register_handlers(learning: LearningManager) -> dict:
    import customer_specs as _customer_specs
    return {
        "remember_query": lambda p: learning.remember_query(
            p.get("question", ""), p.get("sql", ""), p.get("notes", "")
        ),
        "log_correction": lambda p: learning.log_correction(
            p.get("table", ""), p.get("column", ""),
            p.get("wrong_assumption", ""), p.get("correct_meaning", "")
        ),
        "record_discovery": lambda p: learning.record_discovery(
            p.get("category", ""), p.get("key", ""), p.get("value", "")
        ),
        "get_learned_queries": lambda p: learning.get_learned_queries(p.get("search")),
        "get_discoveries": lambda p: learning.get_discoveries(p.get("category")),
        "save_customer_spec": lambda p: _customer_specs.save_spec(
            p.get("customer", ""), p.get("spec_type", "general"),
            p.get("rule", ""), p.get("dc")
        ),
        "get_customer_specs": lambda p: _customer_specs.get_specs(p.get("customer")),
    }
