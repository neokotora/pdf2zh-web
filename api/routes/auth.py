"""Authentication route handlers."""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from pdf2zh_next.api.deps import get_admin_user, get_current_user, get_user_manager
from pdf2zh_next.auth import AuthenticationError
from pdf2zh_next.const import __version__

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


@router.get("/status")
async def check_auth_status():
    """Check if initial setup is required."""
    um = get_user_manager()
    return {"setup_required": not um.has_users(), "version": __version__}


@router.post("/setup")
async def initial_setup(request: SetupRequest):
    """Create the first admin user."""
    um = get_user_manager()
    if um.has_users():
        raise HTTPException(status_code=400, detail="Setup already completed")

    try:
        um.create_user(request.username, request.password, is_admin=True)
        token = um.authenticate(request.username, request.password)
        return {
            "success": True,
            "token": token,
            "username": request.username,
            "is_admin": True,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
async def login(request: LoginRequest):
    """Authenticate user and return session token."""
    um = get_user_manager()
    token = um.authenticate(request.username, request.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_data = um.validate_token(token)
    return {
        "success": True,
        "token": token,
        "username": user_data["username"],
        "is_admin": user_data["is_admin"],
    }


@router.post("/logout")
async def logout(
    current_user: dict = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """Logout current user."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        get_user_manager().logout(token)
    return {"success": True, "message": "Logged out successfully"}


@router.post("/register")
async def register_user(
    request: RegisterRequest, admin_user: dict = Depends(get_admin_user)
):
    """Register a new user (admin only)."""
    try:
        get_user_manager().create_user(request.username, request.password, is_admin=False)
        return {
            "success": True,
            "message": f"User '{request.username}' created successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users")
async def list_users(admin_user: dict = Depends(get_admin_user)):
    """List all users (admin only)."""
    try:
        users = get_user_manager().list_users(admin_user["username"])
        return {"success": True, "users": users}
    except AuthenticationError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/users/{username}")
async def delete_user(username: str, admin_user: dict = Depends(get_admin_user)):
    """Delete a user (admin only)."""
    try:
        get_user_manager().delete_user(username, admin_user["username"])
        return {
            "success": True,
            "message": f"User '{username}' deleted successfully",
        }
    except (AuthenticationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/registration-status")
async def get_registration_status():
    """Check if user registration is enabled (public endpoint)."""
    return {"success": True, "enabled": get_user_manager().get_registration_enabled()}


@router.post("/registration-toggle")
async def toggle_registration(
    request: dict, admin_user: dict = Depends(get_admin_user)
):
    """Enable or disable user registration (admin only)."""
    try:
        enabled = request.get("enabled", False)
        get_user_manager().set_registration_enabled(enabled, admin_user["username"])
        return {
            "success": True,
            "enabled": enabled,
            "message": f"Registration {'enabled' if enabled else 'disabled'}",
        }
    except AuthenticationError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/register/public")
async def register_public(request: RegisterRequest):
    """Public user registration (only works if registration is enabled)."""
    um = get_user_manager()
    if not um.get_registration_enabled():
        raise HTTPException(
            status_code=403,
            detail="User registration is currently disabled. Please contact an administrator.",
        )

    try:
        um.create_user(request.username, request.password, is_admin=False)
        token = um.authenticate(request.username, request.password)
        user_data = um.validate_token(token)
        return {
            "success": True,
            "message": f"Account created successfully! Welcome, {request.username}!",
            "token": token,
            "username": user_data["username"],
            "is_admin": user_data["is_admin"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
