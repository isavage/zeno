import re
import logging
from typing import List, Dict, Any, Optional
from app.config import settings
from app.agent.providers import provider_manager
from app.agent import prefs

logger = logging.getLogger(__name__)

class ModelRouter:
    """Intelligently routes queries based on complexity, cost, and availability."""

    # Keywords signaling high complexity requiring reasoning models
    COMPLEX_PATTERNS = [
        r"\b(code|function|debug|algorithm|architecture|refactor|script|program)\b",
        r"\b(analyze|critique|compare|evaluate|synthesize|derive|proof)\b",
        r"\b(plan|step-by-step|strategy|roadmap)\b",
        r"\b(summarize this document|extract all|parse json)\b",
    ]

    # Simple keywords for fast/free tier
    SIMPLE_PATTERNS = [
        r"^(hi|hello|hey|greetings|howdy|good (morning|afternoon|evening))\b",
        r"^(what time|current time|date today|who are you|what is your name)\b",
        r"^(thanks|thank you|ok|okay|bye|goodbye)\b",
        r"^(convert|calculate|define [a-zA-Z]+)\b",
    ]

    def _model_is_available(self, model_name: str) -> bool:
        client, _, _ = provider_manager.get_client_for_model(model_name)
        return client is not None

    def assess_complexity(self, messages: List[Dict[str, Any]]) -> str:
        """Determines if request is 'simple' (free tier) or 'complex' (reasoning tier)."""
        if not messages:
            return "simple"

        # Extract last user message
        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break

        if not last_user_msg:
            return "simple"

        msg_lower = last_user_msg.lower().strip()
        word_count = len(msg_lower.split())

        # Check simple patterns first
        for pattern in self.SIMPLE_PATTERNS:
            if re.search(pattern, msg_lower):
                return "simple"

        # Check complex patterns or length
        for pattern in self.COMPLEX_PATTERNS:
            if re.search(pattern, msg_lower):
                return "complex"

        if word_count > 60 or "\n" in msg_lower:
            return "complex"

        return "simple"

    def get_candidate_models(self, complexity: str) -> List[str]:
        """Returns prioritized candidate models for the given complexity tier."""
        # Load up-to-date defaults from the prefs DB
        _prefs = prefs.get_prefs()
        fast_default = _prefs["fast_model"]
        reasoning_default = _prefs["reasoning_model"]
        fallback_default = _prefs["fallback_model"]

        candidates: List[str] = []

        if complexity == "simple":
            # Prefer fast/free tier first
            if self._model_is_available(fast_default):
                candidates.append(fast_default)
            if self._model_is_available(fallback_default):
                candidates.append(fallback_default)
            if settings.DEEPSEEK_API_KEY:
                candidates.append("deepseek-chat")
            if settings.OPENAI_API_KEY:
                candidates.append("gpt-5-nano")
            if self._model_is_available("openrouter/free"):
                candidates.append("openrouter/free")
        else:
            # Prefer deep reasoning tier
            if self._model_is_available(reasoning_default):
                candidates.append(reasoning_default)
            if settings.OPENAI_API_KEY:
                candidates.append("gpt-5.6-luna")
            if settings.MOONSHOT_API_KEY:
                candidates.append("moonshot-v1-32k")
            if self._model_is_available("openrouter/free"):
                candidates.append("openrouter/free")
            if self._model_is_available(fallback_default):
                candidates.append(fallback_default)

        # Ensure fallback model is always in list
        if fallback_default not in candidates and self._model_is_available(fallback_default):
            candidates.append(fallback_default)

        return candidates

model_router = ModelRouter()
