import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from app.config import settings
from app.security.encryption import vault_cipher

logger = logging.getLogger(__name__)


class EncryptedMemoryStore:
    """Manages chat history, conversation metadata, and encrypted memories."""

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
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversation_user ON conversations(user_email)")
            conn.commit()

    def _user_email_from_session(self, session_id: str) -> str:
        raw = session_id[4:] if session_id.startswith("web_") else session_id
        return raw.split(":", 1)[0]

    def _default_title(self, session_id: str) -> str:
        if session_id == f"web_{self._user_email_from_session(session_id)}":
            return "Default Chat"
        return "New Chat"

    def _upsert_conversation(self, session_id: str, user_email: str, title: Optional[str] = None):
        final_title = title or self._default_title(session_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversations (session_id, user_email, title, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_email = excluded.user_email,
                    title = CASE
                        WHEN conversations.title IN ('New Chat', 'Default Chat') AND excluded.title != 'New Chat' THEN excluded.title
                        ELSE conversations.title
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, user_email, final_title),
            )
            conn.commit()

    def add_message(self, session_id: str, role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None):
        encrypted_content = vault_cipher.encrypt_text(content or "")
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        user_email = self._user_email_from_session(session_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (session_id, role, encrypted_content, tool_calls) VALUES (?, ?, ?, ?)",
                (session_id, role, encrypted_content, tool_calls_json)
            )
            conn.commit()

        if role == "user":
            preview = (content or "").strip().replace("\n", " ")
            if len(preview) > 36:
                preview = preview[:36].rstrip() + "..."
            self._upsert_conversation(session_id, user_email, preview or self._default_title(session_id))
        else:
            self._upsert_conversation(session_id, user_email)

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
                # Older rows may predate encryption and are stored as plaintext.
                # Treat those as readable history instead of noisy failures.
                if isinstance(enc_content, str) and not enc_content.startswith("gAAAA"):
                    decrypted_content = enc_content
                else:
                    logger.warning(f"Failed to decrypt message in session {session_id}: {e}")
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
            cursor.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_conversations(self, user_email: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, title, created_at, updated_at
                FROM conversations
                WHERE user_email = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (user_email,),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "SELECT title, created_at, updated_at FROM conversations WHERE session_id = ?",
                (f"web_{user_email}",),
            )
            default_row = cursor.fetchone()

        conversations: List[Dict[str, Any]] = [{
            "session_id": f"web_{user_email}",
            "chat_id": "default",
            "title": default_row[0] if default_row else "Default Chat",
            "created_at": default_row[1] if default_row else None,
            "updated_at": default_row[2] if default_row else None,
            "is_default": True,
        }]

        default_session_id = f"web_{user_email}"
        for session_id, title, created_at, updated_at in rows:
            if session_id == default_session_id:
                continue
            conversations.append({
                "session_id": session_id,
                "chat_id": "default" if session_id == default_session_id else session_id.split(":", 1)[1],
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "is_default": session_id == default_session_id,
            })
        return conversations

    def create_conversation(self, user_email: str, chat_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        session_id = f"web_{user_email}" if chat_id == "default" else f"web_{user_email}:{chat_id}"
        self._upsert_conversation(session_id, user_email, title or ("Default Chat" if chat_id == "default" else "New Chat"))
        return {
            "session_id": session_id,
            "chat_id": chat_id,
            "title": title or ("Default Chat" if chat_id == "default" else "New Chat"),
            "is_default": chat_id == "default",
        }


memory_store = EncryptedMemoryStore()
