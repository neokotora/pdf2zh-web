"""
SQLite database connection management and migration.

Provides a singleton database manager that handles:
- Connection pooling via contextmanager
- Schema initialization and migration
- Crash recovery on startup
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("data/users.db")


class DatabaseManager:
    """Manages SQLite connections and schema migrations."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_migrations()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _run_migrations(self):
        """Run all schema migrations."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create tasks table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    file_id TEXT,
                    original_filename TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    mono_path TEXT,
                    dual_path TEXT,
                    error_message TEXT,
                    token_usage TEXT,
                    settings_snapshot TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
                )
            """)

            # Create index on username for history queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_username
                ON tasks(username, created_at DESC)
            """)

            # Create index on status for recovery queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status)
            """)

    def recover_stale_tasks(self):
        """Mark stale queued/processing tasks as failed on startup."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()
            cursor.execute(
                """UPDATE tasks
                   SET status = 'failed',
                       error_message = 'Server restarted during translation',
                       completed_at = ?
                   WHERE status IN ('queued', 'processing')""",
                (now,),
            )
            affected = cursor.rowcount
            if affected > 0:
                logger.info(f"Recovered {affected} stale tasks on startup")

    def migrate_history_json(self, username: str):
        """Migrate a user's history.json into the tasks table."""
        history_file = Path(f"data/users/{username}/history.json")
        if not history_file.exists():
            return

        try:
            history = json.loads(history_file.read_text())
        except (json.JSONDecodeError, OSError):
            return

        if not history:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            migrated = 0
            for item in history:
                task_id = item.get("task_id")
                if not task_id:
                    continue

                # Skip if already migrated
                cursor.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
                )
                if cursor.fetchone():
                    continue

                cursor.execute(
                    """INSERT INTO tasks
                       (task_id, username, file_id, original_filename, status,
                        progress, message, mono_path, dual_path, error_message,
                        created_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task_id,
                        username,
                        item.get("file_id"),
                        item.get("original_filename"),
                        item.get("status", "completed"),
                        100 if item.get("status") == "completed" else 0,
                        "",
                        item.get("mono_path"),
                        item.get("dual_path"),
                        item.get("error"),
                        item.get("created_at", datetime.utcnow().isoformat()),
                        item.get("completed_at"),
                    ),
                )
                migrated += 1

            if migrated > 0:
                logger.info(
                    f"Migrated {migrated} history items for user {username}"
                )
                # Rename old file to mark as migrated
                history_file.rename(history_file.with_suffix(".json.bak"))


# Singleton instance
_db: DatabaseManager | None = None


def get_db() -> DatabaseManager:
    """Get the singleton DatabaseManager instance."""
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
