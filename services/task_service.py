"""
Task lifecycle service: create, update, query, persist.

All task state is stored in SQLite. An in-memory notification channel
(asyncio.Queue per task) supports SSE streaming.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from pdf2zh_next.db.database import get_db

logger = logging.getLogger(__name__)

# In-memory queues for SSE streaming (task_id -> asyncio.Queue)
_task_queues: dict[str, asyncio.Queue] = {}


class TaskService:
    """Manages translation task lifecycle with SQLite persistence."""

    def __init__(self):
        self.db = get_db()

    def create_task(
        self,
        username: str,
        file_id: str,
        original_filename: str,
        settings_snapshot: dict | None = None,
    ) -> str:
        """Create a new task in queued state. Returns task_id."""
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (task_id, username, file_id, original_filename, status,
                    progress, message, settings_snapshot, created_at)
                   VALUES (?, ?, ?, ?, 'queued', 0, 'Translation queued', ?, ?)""",
                (
                    task_id,
                    username,
                    file_id,
                    original_filename,
                    json.dumps(settings_snapshot) if settings_snapshot else None,
                    now,
                ),
            )

        # Create SSE queue
        _task_queues[task_id] = asyncio.Queue()
        return task_id

    def update_progress(
        self,
        task_id: str,
        progress: int,
        message: str,
        status: str = "processing",
    ):
        """Update task progress. Also pushes event to SSE queue."""
        with self.db.get_connection() as conn:
            updates = {
                "progress": progress,
                "message": message,
                "status": status,
            }
            if status == "processing":
                conn.execute(
                    """UPDATE tasks
                       SET progress = ?, message = ?, status = ?,
                           started_at = COALESCE(started_at, ?)
                       WHERE task_id = ?""",
                    (progress, message, status, datetime.utcnow().isoformat(), task_id),
                )
            else:
                conn.execute(
                    """UPDATE tasks SET progress = ?, message = ?, status = ?
                       WHERE task_id = ?""",
                    (progress, message, status, task_id),
                )

        # Push to SSE queue (non-blocking)
        self._push_event(task_id, {
            "type": "progress",
            "progress": progress,
            "message": message,
            "status": status,
        })

    def complete_task(
        self,
        task_id: str,
        mono_path: str | None = None,
        dual_path: str | None = None,
        token_usage: dict | None = None,
    ):
        """Mark task as completed with output paths."""
        now = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status = 'completed', progress = 100,
                       message = 'Translation completed',
                       mono_path = ?, dual_path = ?,
                       token_usage = ?, completed_at = ?
                   WHERE task_id = ?""",
                (
                    mono_path,
                    dual_path,
                    json.dumps(token_usage) if token_usage else None,
                    now,
                    task_id,
                ),
            )

        self._push_event(task_id, {
            "type": "complete",
            "progress": 100,
            "message": "Translation completed",
            "status": "completed",
            "mono_path": mono_path,
            "dual_path": dual_path,
        })

    def fail_task(self, task_id: str, error_message: str):
        """Mark task as failed."""
        now = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status = 'failed', message = ?,
                       error_message = ?, completed_at = ?
                   WHERE task_id = ?""",
                (f"Translation failed: {error_message}", error_message, now, task_id),
            )

        self._push_event(task_id, {
            "type": "error",
            "message": f"Translation failed: {error_message}",
            "status": "failed",
        })

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get a single task by ID."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row:
                return dict(row)
        return None

    def get_user_tasks(self, username: str) -> list[dict]:
        """Get all tasks for a user, newest first."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM tasks
                   WHERE username = ?
                   ORDER BY created_at DESC""",
                (username,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_task(self, task_id: str, username: str) -> bool:
        """Delete a task and its files. Returns True if deleted."""
        import shutil

        task = self.get_task(task_id)
        if not task or task["username"] != username:
            return False

        # Delete output directory
        user_dir = Path(f"data/users/{username}")
        output_dir = user_dir / "outputs" / task_id
        if output_dir.exists():
            shutil.rmtree(output_dir)

        # Delete uploaded file
        file_id = task.get("file_id")
        if file_id:
            upload_dir = user_dir / "uploads"
            for f in upload_dir.glob(f"{file_id}_*"):
                f.unlink()

        # Delete from DB
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

        # Cleanup SSE queue
        _task_queues.pop(task_id, None)
        return True

    def get_task_queue(self, task_id: str) -> Optional[asyncio.Queue]:
        """Get the SSE queue for a task (creates one if needed)."""
        if task_id not in _task_queues:
            _task_queues[task_id] = asyncio.Queue()
        return _task_queues[task_id]

    def cleanup_queue(self, task_id: str):
        """Remove SSE queue after client disconnects."""
        _task_queues.pop(task_id, None)

    def _push_event(self, task_id: str, event: dict):
        """Push event to SSE queue if it exists."""
        q = _task_queues.get(task_id)
        if q:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"SSE queue full for task {task_id}, dropping event")


# Singleton
_task_service: TaskService | None = None


def get_task_service() -> TaskService:
    global _task_service
    if _task_service is None:
        _task_service = TaskService()
    return _task_service
