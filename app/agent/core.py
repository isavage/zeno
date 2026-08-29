import json
import logging
from typing import List, Dict, Any, Optional
from app.config import settings
from app.agent.usage import usage_store
from app.agent.providers import provider_manager
from app.agent.router import model_router
from app.agent.tools import tool_registry
from app.agent.memory import memory_store

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Zeno, an ultra-competent, privacy-first personal AI assistant powered by Hermes architecture.
You are running directly inside your user's private, encrypted personal cloud environment.

Core Guidelines:
1. Tone & Persona: Concise, highly intelligent, proactive, helpful, and direct. Avoid unnecessary conversational fluff.
2. Tools: You have access to tools including notes_vault, web_search, calculator, and get_current_time. Use them when you need real-time data or calculations.
3. Privacy & Security: The user's notes and memory are encrypted at rest. Always treat user information as strictly confidential.
4. Voice & Chat: If responding to voice notes or concise chat, structure your answers clearly with clean markdown formatting.
"""

class HermesAgent:
    """Core Hermes Assistant agent orchestrator."""

    def __init__(self):
        self.system_prompt = SYSTEM_PROMPT

    async def process_query(
        self,
        session_id: str,
        user_message: str,
        max_tool_steps: int = 5
    ) -> Dict[str, Any]:
        """Main processing loop for user requests."""
        # 1. Retrieve history
        history = memory_store.get_recent_history(session_id, limit=10)

        # 2. Add current user message to persistent encrypted memory
        memory_store.add_message(session_id, "user", user_message)

        # 3. Build message sequence
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        # 4. Determine query tier & candidate models
        complexity = model_router.assess_complexity(messages)
        candidate_models = model_router.get_candidate_models(complexity)
        tools = tool_registry.get_openai_schemas()

        last_error = None
        executed_tools: List[str] = []

        # 5. Model execution & fallback loop
        for model_name in candidate_models:
            client, provider_key, target_model = provider_manager.get_client_for_model(model_name)
            if not client:
                continue


            try:
                working_messages = list(messages)
                current_step = 0

                while current_step < max_tool_steps:
                    current_step += 1
                    kwargs: Dict[str, Any] = {
                        "model": target_model,
                        "messages": working_messages,
                    }
                    # Provide tools if model supports it
                    if tools:
                        kwargs["tools"] = tools
                        kwargs["tool_choice"] = "auto"

                    response = await client.chat.completions.create(**kwargs)
                    choice = response.choices[0]
                    message = choice.message

                    # Check if the model requested any tool calls
                    if message.tool_calls:
                        working_messages.append(message.model_dump(exclude_unset=True))

                        for tool_call in message.tool_calls:
                            fn_name = tool_call.function.name
                            executed_tools.append(fn_name)
                            try:
                                fn_args = json.loads(tool_call.function.arguments or "{}")
                            except Exception:
                                fn_args = {}

                            logger.info(f"Agent executing tool: {fn_name} with args: {fn_args}")
                            tool_result = await tool_registry.execute_tool(fn_name, fn_args)

                            working_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": fn_name,
                                "content": json.dumps(tool_result)
                            })
                        # Loop continues to give results back to model
                        continue
                    else:
                        # Model generated final text reply
                        reply_content = message.content or ""
                        memory_store.add_message(session_id, "assistant", reply_content)

                        # Record token usage
                        try:
                            usage = response.usage
                            request_tokens = getattr(usage, "prompt_tokens", 0)
                            response_tokens = getattr(usage, "completion_tokens", 0)
                            total_tokens = getattr(usage, "total_tokens", request_tokens + response_tokens)
                            usage_store.record(
                                user_email=session_id,
                                provider=provider_key,
                                model=target_model,
                                request_tokens=request_tokens,
                                response_tokens=response_tokens,
                                total_tokens=total_tokens,
                            )
                        except Exception as e:
                            logger.debug(f"Failed to record usage: {e}")

                        return {
                            "response": reply_content,
                            "model_used": target_model,
                            "complexity": complexity,
                            "tools_called": executed_tools,
                            "status": "success"
                        }

            except Exception as e:
                logger.warning(f"Provider error on model '{target_model}': {e}. Trying fallback...")
                last_error = str(e)
                continue

        # If all candidates fail
        error_reply = (
            "I'm sorry, I was unable to connect to the language model providers. "
            f"Please verify your API keys in Doppler or .env. (Error: {last_error})"
        )
        memory_store.add_message(session_id, "assistant", error_reply)
        return {
            "response": error_reply,
            "model_used": "none",
            "complexity": complexity,
            "tools_called": executed_tools,
            "status": "error",
            "error": last_error
        }

zeno_agent = HermesAgent()
