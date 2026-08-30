import json
import logging
from pathlib import Path
from threading import Lock
from typing import Dict

from app.config import settings

logger = logging.getLogger(__name__)

_LOCK = Lock()
_PREFS_PATH = settings.vault_path / "model_prefs.json"


def _default_prefs() -> Dict[str, str]:
    return {
        "fast_model": settings.DEFAULT_FAST_MODEL,
        "reasoning_model": settings.DEFAULT_REASONING_MODEL,
        "fallback_model": settings.DEFAULT_FALLBACK_MODEL,
    }


def _load_from_disk() -> Dict[str, str]:
    if not _PREFS_PATH.exists():
        return _default_prefs()

    try:
        with _PREFS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("Failed to load model prefs from %s: %s", _PREFS_PATH, exc)
        return _default_prefs()

    prefs = _default_prefs()
    for key in prefs:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            prefs[key] = value.strip()

    return prefs


def get_prefs() -> Dict[str, str]:
    with _LOCK:
        return dict(_load_from_disk())


def set_prefs(fast_model: str, reasoning_model: str, fallback_model: str) -> Dict[str, str]:
    prefs = {
        "fast_model": fast_model.strip(),
        "reasoning_model": reasoning_model.strip(),
        "fallback_model": fallback_model.strip(),
    }

    with _LOCK:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _PREFS_PATH.open("w", encoding="utf-8") as fh:
            json.dump(prefs, fh, indent=2, sort_keys=True)

    return prefs
