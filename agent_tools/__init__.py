"""
DM03 Data Warehouse Agent Tools
================================
Tool framework for AI agents to query and learn from the data warehouse.

Usage:
    from agent_tools import AgentToolkit

    toolkit = AgentToolkit()
    tools = toolkit.get_tool_definitions()
    result = toolkit.handle_tool_call("execute_sql", {"sql": "SELECT ..."})
"""

from .query_executor import QueryExecutor, TOOL_DEFINITIONS as _query_defs, register_handlers as _query_handlers
from .context_loader import ContextLoader, TOOL_DEFINITIONS as _context_defs, register_handlers as _context_handlers
from .learning import LearningManager, TOOL_DEFINITIONS as _learning_defs, register_handlers as _learning_handlers
from .excel_exporter import ExcelExporter, TOOL_DEFINITIONS as _export_defs, register_handlers as _export_handlers
from .harvest_planner import HarvestPlannerAPI, TOOL_DEFINITIONS as _hp_defs, register_handlers as _hp_handlers
from .living_documents import TOOL_DEFINITIONS as _ld_defs, register_handlers as _ld_handlers
from .pdf_exporter import PDFExporter, TOOL_DEFINITIONS as _pdf_defs, register_handlers as _pdf_handlers
from .o365_tools import TOOL_DEFINITIONS as _o365_defs, register_handlers as _o365_handlers


class AgentToolkit:
    """
    Main interface for AI agent tools.
    Combines query execution, context loading, and learning.
    """

    def __init__(self):
        self.executor = QueryExecutor()
        self.context = ContextLoader()
        self.learning = LearningManager()
        self.exporter = ExcelExporter()
        self.harvest_planner = HarvestPlannerAPI()
        self.pdf_exporter = PDFExporter()

    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for LLM function calling."""
        return (
            _query_defs
            + _context_defs
            + _learning_defs
            + _export_defs
            + _hp_defs
            + _ld_defs
            + _pdf_defs
            + _o365_defs
        )

    def handle_tool_call(self, tool_name: str, parameters: dict) -> dict:
        """Route a tool call to the appropriate handler."""
        handlers = {}
        handlers.update(_query_handlers(self.executor))
        handlers.update(_context_handlers(self.context))
        handlers.update(_learning_handlers(self.learning))
        handlers.update(_export_handlers(self.exporter))
        handlers.update(_hp_handlers(self.harvest_planner))
        handlers.update(_ld_handlers())
        handlers.update(_pdf_handlers(self.pdf_exporter))
        handlers.update(_o365_handlers())

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        return handler(parameters)
