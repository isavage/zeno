import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class UsageStore:
    """Simple SQLite store for per‑user LLM usage metrics.
    The table is created in the same vault directory used for encrypted memory.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.vault_path / "zeno_usage.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    request_tokens INTEGER NOT NULL,
                    response_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def record(self, user_email: str, provider: str, model: str,
               request_tokens: int, response_tokens: int, total_tokens: int):
        """Insert a new usage record.
        All token counts are expected to be non‑negative integers.
        """
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO usage (user_email, provider, model, request_tokens, response_tokens, total_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_email, provider, model, request_tokens, response_tokens, total_tokens),
            )
            conn.commit()

    def get_all(self) -> List[Dict[str, Any]]:
        """Return all usage rows as a list of dicts sorted by newest first."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_email, provider, model, request_tokens, response_tokens, total_tokens, recorded_at"
                " FROM usage ORDER BY recorded_at DESC"
            )
            rows = cur.fetchall()
        columns = [
            "user_email",
            "provider",
            "model",
            "request_tokens",
            "response_tokens",
            "total_tokens",
            "recorded_at",
        ]
        return [dict(zip(columns, row)) for row in rows]


usage_store = UsageStore()

