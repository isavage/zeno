import logging
from typing import List, Dict, Any, Optional, Tuple
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

class LLMProviderManager:
    """Manages clients and configurations for multiple LLM providers."""

    def __init__(self):
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._init_clients()

    def _init_clients(self):
        # OpenAI
        if settings.OPENAI_API_KEY:
            self._clients["openai"] = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY
            )

        # DeepSeek
        if settings.DEEPSEEK_API_KEY:
            self._clients["deepseek"] = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com"
            )

        # Moonshot Kimi
        if settings.MOONSHOT_API_KEY:
            self._clients["kimi"] = AsyncOpenAI(
                api_key=settings.MOONSHOT_API_KEY,
                base_url="https://api.moonshot.cn/v1"
            )

        # OpenRouter / Nous
        if settings.OPENROUTER_API_KEY:
            self._clients["openrouter"] = AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
            )

    def get_client_for_model(self, model_name: str) -> Tuple[Optional[AsyncOpenAI], str, str]:
        """Resolves the appropriate AsyncOpenAI client, provider key, and model name.
        Returns (client, provider_key, effective_model) or (None, "", model_name) if unavailable.
        """
        # DeepSeek
        if model_name.startswith("deepseek") and "deepseek" in self._clients:
            return self._clients["deepseek"], "deepseek", model_name
        # OpenAI models
        elif model_name.startswith("gpt") or model_name.startswith("o1") or model_name.startswith("o3"):
            if "openai" in self._clients:
                return self._clients["openai"], "openai", model_name
        # Moonshot/Kimi
        elif model_name.startswith("moonshot") and "kimi" in self._clients:
            return self._clients["kimi"], "kimi", model_name

        # Default / OpenRouter fallback
        if "openrouter" in self._clients:
            return self._clients["openrouter"], "openrouter", model_name
        elif "openai" in self._clients:
            # fallback to a safe default OpenAI model
            return self._clients["openai"], "openai", "gpt-4o-mini"
        elif "deepseek" in self._clients:
            return self._clients["deepseek"], "deepseek", "deepseek-chat"

        # Fallback to any initialized client
        if self._clients:
            first_key = next(iter(self._clients))
            return self._clients[first_key], first_key, model_name

        return None, "", model_name
    def has_any_provider(self) -> bool:
        return len(self._clients) > 0

provider_manager = LLMProviderManager()
