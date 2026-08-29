import io
import os
import tempfile
import logging
import re
from pathlib import Path
from typing import Optional, Tuple
from app.config import settings

logger = logging.getLogger(__name__)

class TextToSpeech:
    """Open-source Text-to-Speech synthesis using Kokoro-82M or fallback."""

    def __init__(self):
        self._pipeline = None
        self.voice_name = settings.KOKORO_VOICE

    def _clean_markdown_for_speech(self, text: str) -> str:
        """Strips markdown code blocks, links, and formatting symbols for natural speech."""
        # Remove code blocks
        text = re.sub(r"```[\s\S]*?```", " [code block omitted] ", text)
        # Convert markdown links [text](url) to text
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # Remove bold/italic markers
        text = re.sub(r"[*_~`#>]", "", text)
        return text.strip()

    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from kokoro import KPipeline
                logger.info(f"Loading Kokoro TTS pipeline with voice '{self.voice_name}'...")
                self._pipeline = KPipeline(lang_code="a")  # American English
            except Exception as e:
                logger.warning(f"Kokoro TTS not available or failed to load: {e}")
                self._pipeline = False
        return self._pipeline

    def synthesize_to_file(self, text: str, output_path: Path) -> Optional[Path]:
        """Synthesizes text into an audio file (.wav / .ogg / .mp3)."""
        clean_text = self._clean_markdown_for_speech(text)
        if not clean_text:
            return None

        pipeline = self._get_pipeline()
        if not pipeline:
            logger.warning("TTS pipeline not loaded; skipping voice generation.")
            return None

        try:
            import soundfile as sf
            import numpy as np

            generator = pipeline(clean_text, voice=self.voice_name, speed=1.0, split_pattern=r"\n+")
            audio_segments = []

            for _, _, audio in generator:
                audio_segments.append(audio)

            if not audio_segments:
                return None

            combined_audio = np.concatenate(audio_segments)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(output_path), combined_audio, 24000)
            return output_path
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return None

tts_engine = TextToSpeech()
