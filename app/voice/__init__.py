from typing import Optional
from pathlib import Path
import logging

from app.config import settings
from .tts import TextToSpeech as KokoroTTSEngine
from .edge_tts import EdgeTTSEngine

logger = logging.getLogger(__name__)

class TTSEngine:
    """Facade that selects primary TTS provider (Edge) and falls back to Kokoro only on rate‑limit errors.
    The fallback is triggered when the primary engine raises an exception whose message contains "rate limit".
    """

    def __init__(self):
        provider = getattr(settings, "TTS_PROVIDER", "edge")
        if provider == "edge":
            self.primary = EdgeTTSEngine(voice=getattr(settings, "EDGE_TTS_VOICE", "en-US-AriaNeural"))
        else:
            self.primary = KokoroTTSEngine()
        # Fallback always uses Kokoro
        self.fallback = KokoroTTSEngine()

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "rate limit" in msg or "429" in msg

    def synthesize_to_file(self, text: str, out_path: Path) -> Optional[Path]:
        try:
            return self.primary.synthesize_to_file(text, out_path)
        except Exception as e:
            if self._is_rate_limit_error(e):
                logger.warning(f"Edge TTS rate‑limit encountered ({e}); falling back to Kokoro.")
                try:
                    return self.fallback.synthesize_to_file(text, out_path)
                except Exception as e2:
                    logger.error(f"Fallback TTS also failed: {e2}")
                    return None
            else:
                logger.error(f"Edge TTS failed with non‑rate‑limit error: {e}")
                raise

# Export singleton instance used by the rest of the app
tts_engine = TTSEngine()
