"""
Shared FastAPI dependencies: authentication, database access.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Header

from pdf2zh_next.auth import UserManager

# Singleton UserManager
_user_manager: UserManager | None = None


def get_user_manager() -> UserManager:
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager()
    return _user_manager


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> dict:
    """Validate auth token and return current user dict."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "")
    user_data = get_user_manager().validate_token(token)

    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_data


async def get_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Ensure current user is an admin."""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user
