from typing import Optional
from pathlib import Path
import logging

from app.config import settings
from .tts import TextToSpeech as KokoroTTSEngine
from .edge_tts import EdgeTTSEngine

logger = logging.getLogger(__name__)

class TTSEngine:
    """Facade that selects primary TTS provider and falls back to Kokoro.
    Configurable via settings.TTS_PROVIDER ("edge" or "kokoro").
    """

    def __init__(self):
        provider = getattr(settings, "TTS_PROVIDER", "edge")
        # Initialize primary engine based on config
        if provider == "edge":
            self.primary = EdgeTTSEngine(voice=getattr(settings, "EDGE_TTS_VOICE", "en-US-AriaNeural"))
        else:
            self.primary = KokoroTTSEngine()
        # Fallback always uses Kokoro
        self.fallback = KokoroTTSEngine()

    def synthesize_to_file(self, text: str, out_path: Path) -> Optional[Path]:
        try:
            return self.primary.synthesize_to_file(text, out_path)
        except Exception as e:
            logger.warning(f"Primary TTS engine failed ({e}); falling back to Kokoro.")
            try:
                return self.fallback.synthesize_to_file(text, out_path)
            except Exception as e2:
                logger.error(f"Fallback TTS also failed: {e2}")
                return None

# Export singleton instance used by the rest of the app
tts_engine = TTSEngine()
