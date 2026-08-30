import asyncio
import logging
import subprocess
from typing import Any, Dict

from app.agent.tools.base import BaseTool
from app.config import settings

logger = logging.getLogger(__name__)


class DockerTool(BaseTool):
    name = "docker"
    description = (
        "Inspect configured Docker containers and restart them when explicitly requested. "
        "Build, exec, rm, stop, and arbitrary shell commands are not available."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ps", "logs", "inspect", "stats", "restart"],
                "description": "Docker operation to perform.",
            },
            "container": {
                "type": "string",
                "description": "Configured container name, required except for ps.",
            },
            "tail": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "default": 50,
                "description": "Maximum log lines to return for logs.",
            },
        },
        "required": ["action"],
    }

    async def execute(self, action: str, container: str = "", tail: int = 50, **kwargs) -> Any:
        if not settings.ENABLE_DOCKER_TOOL:
            return {"error": "Docker control is disabled."}

        if action not in {"ps", "logs", "inspect", "stats", "restart"}:
            return {"error": f"Unsupported Docker action: {action}"}

        if action == "ps":
            command = ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"]
        else:
            target = container.strip()
            if target not in settings.docker_allowed_containers:
                allowed = ", ".join(settings.docker_allowed_containers) or "none"
                return {"error": f"Container is not allowed. Allowed containers: {allowed}."}

            if action == "logs":
                safe_tail = max(1, min(int(tail), 200))
                command = ["docker", "logs", "--tail", str(safe_tail), target]
            elif action == "inspect":
                command = ["docker", "inspect", target]
            elif action == "stats":
                command = ["docker", "stats", "--no-stream", target]
            else:
                command = ["docker", "restart", target]

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                timeout=settings.DOCKER_COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError:
            return {"error": "Docker CLI is not installed in the Zeno container."}
        except subprocess.TimeoutExpired:
            return {"error": "Docker command timed out."}
        except Exception as exc:
            logger.warning("Docker command failed: %s", exc)
            return {"error": "Docker command could not be executed."}

        output = (result.stdout or result.stderr or "").strip()
        # Keep tool responses bounded so logs and model context cannot grow without limit.
        output = output[-12000:]
        if result.returncode != 0:
            return {"error": output or f"Docker exited with status {result.returncode}"}
        return {"action": action, "container": container or None, "output": output}
