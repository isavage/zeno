from typing import Dict, List, Any
from app.agent.tools.base import BaseTool
from app.agent.tools.calculator import CalculatorTool
from app.agent.tools.time_tool import CurrentTimeTool
from app.agent.tools.web_search import WebSearchTool
from app.agent.tools.notes_vault import NotesVaultTool

class ToolRegistry:
    """Registry managing available tools for the Hermes agent."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        self.register(CalculatorTool())
        self.register(CurrentTimeTool())
        self.register(WebSearchTool())
        self.register(NotesVaultTool())

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool:
        return self._tools.get(name)

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        tool = self.get_tool(name)
        if not tool:
            return {"error": f"Tool '{name}' not found."}
        return await tool.execute(**arguments)

tool_registry = ToolRegistry()
