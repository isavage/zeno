import json
from pathlib import Path
from typing import Dict, Any, List
from app.agent.tools.base import BaseTool
from app.config import settings
from app.security.encryption import vault_cipher

class NotesVaultTool(BaseTool):
    name = "notes_vault"
    description = "Create, search, read, update, or list personal notes in your encrypted vault."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "read", "list", "delete"],
                "description": "Action to perform on notes"
            },
            "title": {
                "type": "string",
                "description": "Title or unique filename of the note"
            },
            "content": {
                "type": "string",
                "description": "Content of the note (required for 'create')"
            }
        },
        "required": ["action"]
    }

    def _get_notes_dir(self) -> Path:
        p = settings.vault_path / "notes"
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def execute(self, action: str, title: str = "", content: str = "", **kwargs) -> Any:
        notes_dir = self._get_notes_dir()

        if action == "list":
            files = list(notes_dir.glob("*.enc"))
            return {"notes": [f.stem for f in files]}

        if not title:
            return {"error": "Missing 'title' parameter for note action."}

        safe_title = "".join(c for c in title if c.isalnum() or c in ("-", "_", " ")).strip()
        note_file = notes_dir / f"{safe_title}.enc"

        if action == "create":
            payload = json.dumps({"title": title, "content": content})
            encrypted = vault_cipher.encrypt_text(payload)
            note_file.write_text(encrypted, encoding="utf-8")
            return {"status": "success", "message": f"Note '{safe_title}' created and encrypted successfully."}

        elif action == "read":
            if not note_file.exists():
                return {"error": f"Note '{safe_title}' does not exist."}
            encrypted = note_file.read_text(encoding="utf-8")
            decrypted = vault_cipher.decrypt_text(encrypted)
            return json.loads(decrypted)

        elif action == "delete":
            if note_file.exists():
                note_file.unlink()
                return {"status": "success", "message": f"Note '{safe_title}' deleted."}
            return {"error": f"Note '{safe_title}' not found."}

        return {"error": f"Unknown action '{action}'"}
