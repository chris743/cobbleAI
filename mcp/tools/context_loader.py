"""Load and search schema documentation for agent context."""

import yaml
from pathlib import Path

from .config import CONFIG


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
        return self.load_file("system_architecture.yaml")

    def load_glossary(self) -> dict:
        return self.load_file("glossary.yaml")

    def load_size_dictionary(self, commodity: str = None) -> dict:
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
        return self.load_file(f"domains/{domain_name}/_domain.yaml")

    def load_table_schema(self, table_name: str) -> dict:
        search_name = table_name.lower()
        search_name = search_name.replace("dbo.", "").replace("rpt.", "").replace("ref.", "")
        search_name = search_name.replace("vw_", "").replace("_", "")

        for yaml_file in self.context_path.rglob("*.yaml"):
            file_stem = yaml_file.stem.lower().replace("vw_", "").replace("_", "")
            if search_name in file_stem or file_stem in search_name:
                with open(yaml_file, 'r') as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict) and "columns" in content:
                        return content

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
        tables = []
        for yaml_file in self.context_path.rglob("*.yaml"):
            content = self.load_file(str(yaml_file.relative_to(self.context_path)))
            if isinstance(content, dict) and content.get("name", "").startswith("dbo."):
                tables.append(content["name"])
        return tables

    def search_context(self, query: str) -> list[dict]:
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
        context_parts = []

        arch = self.load_system_architecture()
        if "error" not in arch:
            context_parts.append("# SYSTEM ARCHITECTURE\n" + yaml.dump(arch))

        glossary = self.load_glossary()
        if "error" not in glossary:
            context_parts.append("# GLOSSARY\n" + yaml.dump(glossary))

        for yaml_file in self.context_path.rglob("*.yaml"):
            if yaml_file.name.startswith("vw_") or yaml_file.name.startswith("bininv"):
                with open(yaml_file, 'r') as f:
                    context_parts.append(f"# TABLE: {yaml_file.stem}\n" + f.read())

        return "\n\n---\n\n".join(context_parts)


TOOL_DEFINITIONS = [
    {
        "name": "get_system_architecture",
        "description": "Load the system architecture document. Contains critical info about CF/LP systems, join rules, and column naming conventions. READ THIS FIRST before writing queries.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "get_glossary",
        "description": "Load the business glossary with definitions for domain terms like Bin, Carton, Pool, Grower, Packout, etc.",
        "parameters": {"type": "object", "properties": {}}
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
        "parameters": {"type": "object", "properties": {}}
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
]


def register_handlers(context: ContextLoader) -> dict:
    return {
        "get_system_architecture": lambda p: context.load_system_architecture(),
        "get_glossary": lambda p: context.load_glossary(),
        "get_size_dictionary": lambda p: context.load_size_dictionary(p.get("commodity")),
        "get_table_schema": lambda p: context.load_table_schema(p.get("table_name", "")),
        "search_context": lambda p: context.search_context(p.get("query", "")),
        "list_available_tables": lambda p: context.list_tables(),
    }
