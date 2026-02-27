"""
Auth service: thin wrapper around UserManager for dependency injection.

Re-exports UserManager and AuthenticationError for convenience.
"""

from pdf2zh_next.auth import AuthenticationError
from pdf2zh_next.auth import UserManager

__all__ = ["UserManager", "AuthenticationError"]
