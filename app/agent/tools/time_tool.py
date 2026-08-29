from datetime import datetime
import zoneinfo
from typing import Dict, Any
from app.agent.tools.base import BaseTool

class CurrentTimeTool(BaseTool):
    name = "get_current_time"
    description = "Get the current date, time, day of the week, and timezone information."
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "Optional IANA timezone name (e.g. 'America/New_York', 'Asia/Kolkata', 'UTC'). Defaults to UTC.",
                "default": "UTC"
            }
        }
    }

    async def execute(self, timezone: str = "UTC", **kwargs) -> Any:
        try:
            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.now(tz)
            return {
                "timezone": timezone,
                "iso": now.isoformat(),
                "formatted": now.strftime("%A, %B %d, %Y %I:%M:%S %p"),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
            }
        except Exception as e:
            return {"error": f"Invalid timezone '{timezone}': {str(e)}"}
