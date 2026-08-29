import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from app.config import settings
from app.security.encryption import vault_cipher

logger = logging.getLogger(__name__)

class EncryptedMemoryStore:
    """Manages chat history and user memories with field-level encryption."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.vault_path / "zeno_memory.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    encrypted_content TEXT NOT NULL,
                    tool_calls TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    encrypted_key TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id)")
            conn.commit()

    def add_message(self, session_id: str, role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None):
        encrypted_content = vault_cipher.encrypt_text(content or "")
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (session_id, role, encrypted_content, tool_calls) VALUES (?, ?, ?, ?)",
                (session_id, role, encrypted_content, tool_calls_json)
            )
            conn.commit()

    def get_recent_history(self, session_id: str, limit: int = 12) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, encrypted_content, tool_calls FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit)
            )
            rows = cursor.fetchall()

        messages = []
        for role, enc_content, tool_calls_json in reversed(rows):
            try:
                decrypted_content = vault_cipher.decrypt_text(enc_content)
            except Exception as e:
                logger.error(f"Failed to decrypt message in session {session_id}: {e}")
                decrypted_content = "[Encrypted message unreadable]"

            msg: Dict[str, Any] = {"role": role, "content": decrypted_content}
            if tool_calls_json:
                try:
                    msg["tool_calls"] = json.loads(tool_calls_json)
                except Exception:
                    pass
            messages.append(msg)
        return messages

    def clear_history(self, session_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()

memory_store = EncryptedMemoryStore()
