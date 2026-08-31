from collections import defaultdict
from typing import Any

from app.agent.tools.base import BaseTool
from app.agent.usage import usage_store


class UsageReportTool(BaseTool):
    name = "usage_report"
    description = "Read the local Zeno API usage records and summarize token usage by provider and model."
    parameters = {
        "type": "object",
        "properties": {
            "include_records": {
                "type": "boolean",
                "default": False,
                "description": "Include recent individual usage records in addition to totals.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 20,
                "description": "Maximum recent records to include.",
            },
        },
    }

    async def execute(
        self,
        include_records: bool = False,
        limit: int = 20,
        **kwargs,
    ) -> Any:
        rows = usage_store.get_all()
        by_provider = defaultdict(lambda: {"requests": 0, "total_tokens": 0})
        by_model = defaultdict(lambda: {"requests": 0, "total_tokens": 0})

        total_tokens = 0
        request_tokens = 0
        response_tokens = 0
        for row in rows:
            total_tokens += row["total_tokens"]
            request_tokens += row["request_tokens"]
            response_tokens += row["response_tokens"]

            provider = by_provider[row["provider"]]
            provider["requests"] += 1
            provider["total_tokens"] += row["total_tokens"]

            model = by_model[row["model"]]
            model["requests"] += 1
            model["total_tokens"] += row["total_tokens"]

        result = {
            "requests": len(rows),
            "request_tokens": request_tokens,
            "response_tokens": response_tokens,
            "total_tokens": total_tokens,
            "by_provider": dict(by_provider),
            "by_model": dict(by_model),
        }
        if include_records:
            safe_limit = max(1, min(int(limit), 100))
            result["recent_records"] = rows[:safe_limit]
        return result
