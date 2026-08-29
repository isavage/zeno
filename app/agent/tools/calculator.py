import math
from typing import Dict, Any
from app.agent.tools.base import BaseTool

class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Safely evaluate mathematical expressions and scientific calculations."
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The math expression to evaluate, e.g., '125 * 48 + math.sqrt(144)'"
            }
        },
        "required": ["expression"]
    }

    async def execute(self, expression: str, **kwargs) -> Any:
        allowed_names = {
            k: v for k, v in math.__dict__.items() if not k.startswith("__")
        }
        allowed_names.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
        try:
            # Safely compile and eval with restricted scope
            code = compile(expression, "<string>", "eval")
            for name in code.co_names:
                if name not in allowed_names:
                    return f"Error: Access to '{name}' is disallowed."
            result = eval(code, {"__builtins__": {}}, allowed_names)
            return {"result": result}
        except Exception as e:
            return {"error": f"Evaluation error: {str(e)}"}
