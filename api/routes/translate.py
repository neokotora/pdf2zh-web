"""
Translation route handlers: upload, translate, SSE stream, download, history.
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from pdf2zh_next.api.deps import get_current_user, get_user_manager
from pdf2zh_next.services.task_service import get_task_service
from pdf2zh_next.services.translation_service import run_translation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["translate"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload a PDF file for translation."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    um = get_user_manager()
    user_dir = um.get_user_dir(current_user["username"])
    upload_dir = user_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    file_path = upload_dir / f"{file_id}_{file.filename}"

    with file_path.open("wb") as f:
        content = await file.read()
        f.write(content)

    return {
        "success": True,
        "file_id": file_id,
        "filename": file.filename,
        "file_path": str(file_path),
    }


@router.post("/translate")
async def start_translation(
    file_id: str = Form(...),
    settings: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    """Start a translation task."""
    try:
        translation_settings = json.loads(settings)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid settings JSON")

    um = get_user_manager()
    user_dir = um.get_user_dir(current_user["username"])
    upload_dir = user_dir / "uploads"

    matching_files = list(upload_dir.glob(f"{file_id}_*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = matching_files[0]

    # Create output directory
    task_service = get_task_service()
    task_id = task_service.create_task(
        username=current_user["username"],
        file_id=file_id,
        original_filename=file_path.stem,
        settings_snapshot=translation_settings,
    )

    output_dir = user_dir / "outputs" / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Start translation in background
    asyncio.create_task(
        run_translation(
            task_id, file_path, output_dir, translation_settings, current_user["username"]
        )
    )

    return {"success": True, "task_id": task_id, "message": "Translation started"}


@router.get("/translate/status/{task_id}")
async def get_translation_status(
    task_id: str, current_user: dict = Depends(get_current_user)
):
    """Get status of a translation task (polling fallback)."""
    task_service = get_task_service()
    task = task_service.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["username"] != current_user["username"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Build response compatible with old format
    response_task = {
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "username": task["username"],
        "file_id": task["file_id"],
        "created_at": task["created_at"],
        "original_filename": task["original_filename"],
    }

    if task["status"] == "completed":
        response_task["output_files"] = {
            "mono": task["mono_path"],
            "dual": task["dual_path"],
        }

    return {"success": True, "task": response_task}


@router.get("/translate/stream/{task_id}")
async def stream_translation_progress(
    task_id: str,
    token: str = Query(..., description="JWT token for SSE auth"),
):
    """SSE endpoint for real-time translation progress."""
    # Validate token via query param (EventSource can't set headers)
    um = get_user_manager()
    user_data = um.validate_token(token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    task_service = get_task_service()
    task = task_service.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["username"] != user_data["username"]:
        raise HTTPException(status_code=403, detail="Access denied")

    async def event_generator():
        queue = task_service.get_task_queue(task_id)
        try:
            # Send initial state
            yield {
                "event": "progress",
                "data": json.dumps({
                    "progress": task["progress"],
                    "message": task["message"],
                    "status": task["status"],
                }),
            }

            # If already terminal, send final event and stop
            if task["status"] in ("completed", "failed"):
                yield {
                    "event": task["status"],
                    "data": json.dumps({
                        "progress": task["progress"],
                        "message": task["message"],
                        "status": task["status"],
                        "mono_path": task.get("mono_path"),
                        "dual_path": task.get("dual_path"),
                    }),
                }
                return

            # Stream events from queue
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "ping", "data": ""}
                    continue

                event_type = event.get("type", "progress")
                yield {
                    "event": event_type,
                    "data": json.dumps(event),
                }

                # Stop on terminal events
                if event.get("status") in ("completed", "failed"):
                    break
        finally:
            task_service.cleanup_queue(task_id)

    return EventSourceResponse(event_generator())


@router.get("/translate/history")
async def get_translation_history(current_user: dict = Depends(get_current_user)):
    """Get current user's translation history."""
    task_service = get_task_service()

    # Migrate history.json on first access
    from pdf2zh_next.db.database import get_db

    get_db().migrate_history_json(current_user["username"])

    tasks = task_service.get_user_tasks(current_user["username"])

    # Convert to history format for backward compatibility
    history = []
    for t in tasks:
        item = {
            "task_id": t["task_id"],
            "file_id": t["file_id"],
            "filename": t["original_filename"] or "",
            "original_filename": t["original_filename"],
            "created_at": t["created_at"],
            "completed_at": t["completed_at"],
            "status": t["status"],
            "mono_path": t["mono_path"],
            "dual_path": t["dual_path"],
        }
        if t["error_message"]:
            item["error"] = t["error_message"]
        history.append(item)

    return {"success": True, "history": history}


@router.delete("/translate/history/{task_id}")
async def delete_history_item(
    task_id: str, current_user: dict = Depends(get_current_user)
):
    """Delete a history item and its associated files."""
    task_service = get_task_service()
    deleted = task_service.delete_task(task_id, current_user["username"])

    if not deleted:
        raise HTTPException(status_code=404, detail="History item not found")

    return {"success": True, "message": "History item deleted"}


@router.get("/translate/download/{task_id}")
async def download_translation(
    task_id: str,
    file_type: str = "mono",
    current_user: dict = Depends(get_current_user),
):
    """Download a translated file."""
    task_service = get_task_service()
    task = task_service.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["username"] != current_user["username"]:
        raise HTTPException(status_code=403, detail="Access denied")

    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Translation not completed")

    file_path = task.get(f"{file_type}_path")
    original_filename = task.get("original_filename", "translated")

    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Clean filename
    if original_filename.lower().endswith(".pdf"):
        original_filename = original_filename[:-4]
    if "_" in original_filename:
        parts = original_filename.split("_", 1)
        if len(parts[0]) >= 32 or (len(parts[0]) == 36 and "-" in parts[0]):
            original_filename = parts[1] if len(parts) > 1 else original_filename

    clean_name = re.sub(r"[^\w\-\u4e00-\u9fff\.]", "_", original_filename)
    download_filename = f"{clean_name}_{file_type}.pdf"

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=download_filename,
    )
