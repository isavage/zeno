import asyncio
import logging
import subprocess
from typing import Any

from app.agent.tools.base import BaseTool
from app.config import settings

logger = logging.getLogger(__name__)


class TerminalTool(BaseTool):
    name = "terminal"
    description = (
        "Run a terminal command inside the Zeno application container. Use for diagnostics "
        "and maintenance. Commands are not run on the VPS host directly."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run inside the Zeno container.",
            },
            "working_directory": {
                "type": "string",
                "enum": ["/app", "/data/vault", "/tmp"],
                "default": "/app",
                "description": "Allowed container working directory.",
            },
        },
        "required": ["command"],
    }

    async def execute(
        self,
        command: str,
        working_directory: str = "/app",
        **kwargs,
    ) -> Any:
        if not settings.ENABLE_TERMINAL_TOOL:
            return {"error": "Terminal access is disabled."}

        command = command.strip()
        if not command:
            return {"error": "The terminal command cannot be empty."}
        if len(command) > 2000:
            return {"error": "The terminal command is too long."}

        allowed_directories = {"/app", "/data/vault", "/tmp"}
        if working_directory not in allowed_directories:
            return {"error": "Working directory is not allowed."}

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["/bin/sh", "-lc", command],
                cwd=working_directory,
                capture_output=True,
                text=True,
                timeout=settings.TERMINAL_COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": "Terminal command timed out."}
        except Exception as exc:
            logger.warning("Terminal command failed: %s", exc)
            return {"error": "Terminal command could not be executed."}

        output = (result.stdout or "")
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        output = output.strip()[-20000:]
        return {
            "working_directory": working_directory,
            "exit_code": result.returncode,
            "output": output,
        }
