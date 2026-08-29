import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
from app.config import settings

logger = logging.getLogger(__name__)

class EncryptionVault:
    """Provides at-rest AES-256 (Fernet) encryption for files and database payloads."""

    def __init__(self, key_str: Optional[str] = None):
        self._fernet = self._init_fernet(key_str or settings.ZENOS_ENCRYPTION_KEY)

    def _init_fernet(self, key_str: Optional[str]) -> Fernet:
        if not key_str:
            # Ephemeral fallback for local dev if key is omitted
            logger.warning(
                "ZENOS_ENCRYPTION_KEY not set in environment! Generating a temporary ephemeral key. "
                "For persistent encryption across restarts, define ZENOS_ENCRYPTION_KEY via Doppler."
            )
            return Fernet(Fernet.generate_key())

        # Ensure valid Fernet key (32 url-safe base64-encoded bytes)
        try:
            # Check if it's already a valid Fernet key
            key_bytes = key_str.strip().encode("utf-8")
            if len(key_bytes) == 44:
                return Fernet(key_bytes)
        except Exception:
            pass

        # Derive a deterministic 32-byte key using SHA-256 if custom string provided
        derived_key = base64.urlsafe_b64encode(hashlib.sha256(key_str.encode("utf-8")).digest())
        return Fernet(derived_key)

    def encrypt_bytes(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt_bytes(self, cipher_data: bytes) -> bytes:
        return self._fernet.decrypt(cipher_data)

    def encrypt_text(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("utf-8")

    def decrypt_text(self, cipher_text: str) -> str:
        return self._fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")

    def encrypt_file(self, source_path: Path, dest_path: Path) -> None:
        raw_bytes = source_path.read_bytes()
        encrypted = self.encrypt_bytes(raw_bytes)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(encrypted)

    def decrypt_file(self, encrypted_path: Path, dest_path: Path) -> None:
        encrypted_bytes = encrypted_path.read_bytes()
        decrypted = self.decrypt_bytes(encrypted_bytes)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(decrypted)

vault_cipher = EncryptionVault()
