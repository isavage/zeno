import io
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

class SpeechToText:
    """Open-source Speech-to-Text transcriber using faster-whisper."""

    def __init__(self):
        self._model = None
        self.model_size = settings.WHISPER_MODEL_SIZE

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                logger.info(f"Loading faster-whisper model: {self.model_size} (CPU/CTranslate2)...")
                # compute_type="int8" runs smoothly on any low-cost VPS CPU
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            except Exception as e:
                logger.error(f"Failed to load faster-whisper model: {e}")
                raise
        return self._model

    def transcribe_file(self, audio_path: Path) -> str:
        """Transcribes an audio file into text."""
        model = self._get_model()
        segments, info = model.transcribe(str(audio_path), beam_size=5)
        text_parts = [segment.text for segment in segments]
        transcription = " ".join(text_parts).strip()
        logger.info(f"Transcribed audio ({info.language}, prob={info.language_probability:.2f}): {transcription}")
        return transcription

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".ogg") -> str:
        """Transcribes raw audio bytes by temporarily caching to an ephemeral file."""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        try:
            return self.transcribe_file(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

stt_engine = SpeechToText()
