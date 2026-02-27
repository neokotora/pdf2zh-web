"""Settings route handlers."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path

from pdf2zh_next.api.deps import get_current_user
from pdf2zh_next.auth import AuthenticationError
from pdf2zh_next.services.settings_service import get_settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings(current_user: dict = Depends(get_current_user)):
    """Get current user's settings."""
    svc = get_settings_service()
    settings = await svc.get_settings(current_user["username"])
    return {"success": True, "settings": settings}


@router.post("")
async def update_settings(
    settings: dict, current_user: dict = Depends(get_current_user)
):
    """Update current user's settings."""
    svc = get_settings_service()
    await svc.update_settings(current_user["username"], settings)
    return {"success": True, "message": "Settings updated successfully"}


@router.post("/password")
async def change_password(request: dict, current_user: dict = Depends(get_current_user)):
    """Change current user's password."""
    from pdf2zh_next.api.deps import get_user_manager

    try:
        get_user_manager().change_password(
            current_user["username"],
            request.get("old_password", ""),
            request.get("new_password", ""),
        )
        return {"success": True, "message": "Password changed successfully"}
    except (AuthenticationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reset")
async def reset_settings(current_user: dict = Depends(get_current_user)):
    """Reset current user's settings to default."""
    svc = get_settings_service()
    await svc.reset_settings(current_user["username"])
    return {"success": True, "message": "Settings reset to default"}


@router.get("/export")
async def export_settings(current_user: dict = Depends(get_current_user)):
    """Export current user's settings as JSON file."""
    svc = get_settings_service()
    temp_path, filename = await svc.export_settings(current_user["username"])
    return FileResponse(
        temp_path,
        media_type="application/json",
        filename=filename,
        background=lambda: Path(temp_path).unlink(),
    )


@router.post("/import")
async def import_settings(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Import settings from JSON file."""
    import json
    import logging

    logger = logging.getLogger(__name__)

    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are allowed")

    try:
        content = await file.read()
        svc = get_settings_service()
        meta = await svc.import_settings(current_user["username"], content)
        return {
            "success": True,
            "message": f"Successfully imported {meta['imported_count']} settings",
            **meta,
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to import settings: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to import settings: {str(e)}"
        )
