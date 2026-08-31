from typing import Dict, List, Any
from app.agent.tools.base import BaseTool
from app.config import settings
from app.agent.tools.calculator import CalculatorTool
from app.agent.tools.time_tool import CurrentTimeTool
from app.agent.tools.web_search import WebSearchTool
from app.agent.tools.notes_vault import NotesVaultTool
from app.agent.tools.docker_tool import DockerTool
from app.agent.tools.terminal_tool import TerminalTool
from app.agent.tools.usage_report import UsageReportTool

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
        self.register(UsageReportTool())
        if settings.ENABLE_DOCKER_TOOL:
            self.register(DockerTool())
        if settings.ENABLE_TERMINAL_TOOL:
            self.register(TerminalTool())

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool:
        return self._tools.get(name)

    def _docker_allowed_for_session(self, session_id: str) -> bool:
        if not settings.ENABLE_DOCKER_TOOL or not session_id.startswith("web_"):
            return False
        email = session_id[4:].split(":", 1)[0].strip().lower()
        return bool(email and email in settings.admin_emails)

    def _admin_tool_allowed_for_session(self, session_id: str, telegram_username: str = "") -> bool:
        if session_id.startswith("web_"):
            email = session_id[4:].split(":", 1)[0].strip().lower()
            return bool(email and email in settings.admin_emails)
        if session_id.startswith("tg_"):
            raw_user_id = session_id[3:].strip()
            if raw_user_id.isdigit() and int(raw_user_id) in settings.telegram_admin_user_ids:
                return True
            username = telegram_username.strip().lstrip("@").lower()
            return bool(username and username in settings.telegram_admin_users)
        return False

    def get_openai_schemas(self, session_id: str = "", telegram_username: str = "") -> List[Dict[str, Any]]:
        return [
            tool.to_openai_tool()
            for tool in self._tools.values()
            if tool.name not in {"docker", "terminal", "usage_report"}
            or self._admin_tool_allowed_for_session(session_id, telegram_username)
        ]

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        session_id: str = "",
        telegram_username: str = "",
    ) -> Any:
        tool = self.get_tool(name)
        if not tool:
            return {"error": f"Tool '{name}' not found."}
        if name == "docker" and not self._admin_tool_allowed_for_session(session_id, telegram_username):
            return {"error": "Docker control is restricted to admin users."}
        if name == "terminal" and not self._admin_tool_allowed_for_session(session_id, telegram_username):
            return {"error": "Terminal access is restricted to admin users."}
        if name == "usage_report" and not self._admin_tool_allowed_for_session(session_id, telegram_username):
            return {"error": "Usage reports are restricted to admin users."}
        return await tool.execute(**arguments)

tool_registry = ToolRegistry()
