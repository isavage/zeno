import asyncio
from pathlib import Path
from typing import Optional
import edge_tts
import logging

logger = logging.getLogger(__name__)

class EdgeTTSEngine:
    def __init__(self, voice: str = "en-US-AriaNeural"):
        self.voice = voice

    async def _synthesize(self, text: str) -> bytes:
        communicate = edge_tts.Communicate(text, self.voice)
        audio_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes += chunk["data"]
        return audio_bytes

    def synthesize_to_file(self, text: str, out_path: Path) -> Optional[Path]:
        if not text:
            return None
        try:
            mp3 = asyncio.run(self._synthesize(text))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(mp3)
            return out_path
        except Exception as e:
            logger.warning(f"Edge TTS failed: {e}")
            raise

