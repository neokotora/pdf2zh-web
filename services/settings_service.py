"""
User settings CRUD service with Fernet encryption.

Settings are encrypted using a key derived from the app's SECRET_KEY
(stored in the SQLite app_config table). The encrypted blob is stored
in the user_configs table rather than a plain JSON file.

For backward compatibility, on first access for a user, if settings.json
exists but user_configs does not, the file contents are migrated into
the encrypted store and the JSON file is removed.
"""

import asyncio
import base64
import hashlib
import json
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

from pdf2zh_next.db.database import get_db

logger = logging.getLogger(__name__)


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the app secret."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    """Get a Fernet instance using the app's secret key."""
    db = get_db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_config WHERE key = 'secret_key'"
        ).fetchone()
        if not row:
            raise RuntimeError("No secret_key found in app_config")
        secret = row["value"]
    return Fernet(_derive_fernet_key(secret))


class SettingsService:
    """Manages user translation settings with encrypted storage."""

    # ---- public API ----

    async def get_settings(self, username: str) -> dict:
        """Get decrypted user settings."""
        encrypted = self._read_encrypted(username)
        if encrypted is not None:
            return self._decrypt(encrypted)

        # Fallback: migrate from settings.json if it exists
        json_settings = await self._read_json(username)
        if json_settings:
            await self.update_settings(username, json_settings)
            self._remove_json(username)
        return json_settings

    async def update_settings(self, username: str, settings: dict):
        """Encrypt and save user settings."""
        encrypted = self._encrypt(settings)
        self._write_encrypted(username, encrypted)

    async def reset_settings(self, username: str):
        """Reset user settings to empty."""
        await self.update_settings(username, {})

    async def export_settings(self, username: str) -> tuple[str, str]:
        """Export settings as a temp JSON file. Returns (path, filename)."""
        settings = await self.get_settings(username)
        export_data = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "exported_by": username,
            "settings": settings,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
            temp_path = f.name

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"translation_config_{timestamp}.json"
        return temp_path, filename

    async def import_settings(self, username: str, content: bytes) -> dict:
        """Import settings from JSON content. Returns import metadata."""
        import_data = json.loads(content.decode("utf-8"))

        if "settings" not in import_data:
            raise ValueError(
                "Invalid configuration file: missing 'settings' field"
            )

        if "version" in import_data and import_data["version"] != "1.0":
            logger.warning(
                f"Importing config with version: {import_data['version']}"
            )

        imported_settings = import_data["settings"]
        await self.update_settings(username, imported_settings)

        return {
            "imported_count": len(imported_settings),
            "imported_from": import_data.get("exported_by", "unknown"),
            "exported_at": import_data.get("exported_at", "unknown"),
        }

    # ---- private: encryption helpers ----

    def _encrypt(self, data: dict) -> str:
        """Encrypt a dict to a base64 string."""
        f = _get_fernet()
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return f.encrypt(plaintext).decode("ascii")

    def _decrypt(self, token: str) -> dict:
        """Decrypt a base64 token back to a dict."""
        f = _get_fernet()
        plaintext = f.decrypt(token.encode("ascii"))
        return json.loads(plaintext.decode("utf-8"))

    # ---- private: SQLite storage ----

    def _read_encrypted(self, username: str) -> str | None:
        """Read encrypted settings from user_configs table."""
        db = get_db()
        with db.get_connection() as conn:
            row = conn.execute(
                """SELECT config_value FROM user_configs
                   WHERE username = ? AND config_key = 'settings'""",
                (username,),
            ).fetchone()
            return row["config_value"] if row else None

    def _write_encrypted(self, username: str, encrypted: str):
        """Write encrypted settings to user_configs table."""
        db = get_db()
        now = datetime.utcnow().isoformat()
        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO user_configs (username, config_key, config_value, updated_at)
                   VALUES (?, 'settings', ?, ?)
                   ON CONFLICT(username, config_key) DO UPDATE
                   SET config_value = excluded.config_value,
                       updated_at = excluded.updated_at""",
                (username, encrypted, now),
            )

    # ---- private: JSON file migration ----

    async def _read_json(self, username: str) -> dict:
        """Read settings from the legacy JSON file."""
        path = Path(f"data/users/{username}/settings.json")
        if path.exists():
            return json.loads(await asyncio.to_thread(path.read_text))
        return {}

    def _remove_json(self, username: str):
        """Remove the legacy settings.json after migration."""
        path = Path(f"data/users/{username}/settings.json")
        if path.exists():
            backup = path.with_suffix(".json.bak")
            path.rename(backup)
            logger.info(
                f"Migrated settings.json to encrypted storage for {username}"
            )


# Singleton
_settings_service: SettingsService | None = None


def get_settings_service() -> SettingsService:
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service
