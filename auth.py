"""
Multi-user authentication system for PDFMathTranslate web UI.

This module provides:
- User registration and management
- Password hashing with bcrypt
- JWT-based session management
- User-specific configuration isolation
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import bcrypt
import jwt

# Configuration
SECRET_KEY = secrets.token_urlsafe(32)  # Will be generated on first run
TOKEN_EXPIRY_HOURS = 24
DB_PATH = Path("data/users.db")


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass


class UserManager:
    """Manages user authentication and database operations"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self._load_or_create_secret()
    
    def _init_database(self):
        """Initialize the SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            )
        """)
        
        # User configs table (for storing user-specific settings)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                config_key TEXT NOT NULL,
                config_value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(username, config_key),
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            )
        """)
        
        # App config table (for storing app-level settings like secret key)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _load_or_create_secret(self):
        """Load existing secret key or create a new one"""
        global SECRET_KEY
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM app_config WHERE key = 'secret_key'")
        result = cursor.fetchone()
        
        if result:
            SECRET_KEY = result[0]
        else:
            SECRET_KEY = secrets.token_urlsafe(32)
            cursor.execute(
                "INSERT INTO app_config (key, value) VALUES ('secret_key', ?)",
                (SECRET_KEY,)
            )
            conn.commit()
        
        conn.close()
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash"""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def has_users(self) -> bool:
        """Check if any users exist in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    
    def create_user(self, username: str, password: str, is_admin: bool = False) -> bool:
        """
        Create a new user
        
        Args:
            username: Username for the new user
            password: Password for the new user
            is_admin: Whether the user should have admin privileges
            
        Returns:
            True if user was created successfully
            
        Raises:
            ValueError: If username already exists or is invalid
        """
        if not username or len(username) < 3:
            raise ValueError("Username must be at least 3 characters long")
        
        if not password or len(password) < 6:
            raise ValueError("Password must be at least 6 characters long")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            password_hash = self._hash_password(password)
            created_at = datetime.utcnow().isoformat()
            
            cursor.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, created_at)
            )
            conn.commit()
            
            # Create user data directory
            user_dir = Path(f"data/users/{username}")
            user_dir.mkdir(parents=True, exist_ok=True)
            (user_dir / "uploads").mkdir(exist_ok=True)
            (user_dir / "outputs").mkdir(exist_ok=True)
            
            # Create default settings file
            settings_file = user_dir / "settings.json"
            if not settings_file.exists():
                settings_file.write_text("{}")
            
            # Create history file
            history_file = user_dir / "history.json"
            if not history_file.exists():
                history_file.write_text("[]")
            
            return True
            
        except sqlite3.IntegrityError:
            raise ValueError(f"Username '{username}' already exists")
        finally:
            conn.close()
    
    def authenticate(self, username: str, password: str) -> Optional[str]:
        """
        Authenticate a user and create a session token
        
        Args:
            username: Username to authenticate
            password: Password to verify
            
        Returns:
            Session token if authentication successful, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT password_hash, is_admin FROM users WHERE username = ?",
            (username,)
        )
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return None
        
        password_hash, is_admin = result
        
        if not self._verify_password(password, password_hash):
            conn.close()
            return None
        
        # Update last login
        cursor.execute(
            "UPDATE users SET last_login = ? WHERE username = ?",
            (datetime.utcnow().isoformat(), username)
        )
        
        # Create session token
        expires_at = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
        token_data = {
            'username': username,
            'is_admin': bool(is_admin),
            'exp': expires_at.timestamp()
        }
        
        session_token = jwt.encode(token_data, SECRET_KEY, algorithm='HS256')
        
        # Store session in database
        cursor.execute(
            "INSERT INTO sessions (session_token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_token, username, datetime.utcnow().isoformat(), expires_at.isoformat())
        )
        
        conn.commit()
        conn.close()
        
        return session_token
    
    def validate_token(self, token: str) -> Optional[dict]:
        """
        Validate a session token
        
        Args:
            token: Session token to validate
            
        Returns:
            User data dict if valid, None otherwise
        """
        try:
            # Decode JWT token
            payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            
            # Check if session exists in database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT username, expires_at FROM sessions WHERE session_token = ?",
                (token,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None
            
            username, expires_at = result
            
            # Check if session has expired
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                self.logout(token)
                return None
            
            return {
                'username': username,
                'is_admin': payload.get('is_admin', False)
            }
            
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def logout(self, token: str) -> bool:
        """
        Logout a user by invalidating their session token
        
        Args:
            token: Session token to invalidate
            
        Returns:
            True if logout successful
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
        conn.commit()
        conn.close()
        
        return True
    
    def delete_user(self, username: str, admin_username: str) -> bool:
        """
        Delete a user (admin only)
        
        Args:
            username: Username to delete
            admin_username: Username of the admin performing the deletion
            
        Returns:
            True if deletion successful
            
        Raises:
            AuthenticationError: If admin_username is not an admin
            ValueError: If trying to delete the last admin
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if requester is admin
        cursor.execute("SELECT is_admin FROM users WHERE username = ?", (admin_username,))
        result = cursor.fetchone()
        if not result or not result[0]:
            conn.close()
            raise AuthenticationError("Only admins can delete users")
        
        # Check if target user exists
        cursor.execute("SELECT is_admin FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        if not result:
            conn.close()
            raise ValueError(f"User '{username}' does not exist")
        
        # Check if deleting last admin
        if result[0]:  # If target is admin
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
            admin_count = cursor.fetchone()[0]
            if admin_count <= 1:
                conn.close()
                raise ValueError("Cannot delete the last admin user")
        
        # Delete user
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        
        # Delete user data directory
        user_dir = Path(f"data/users/{username}")
        if user_dir.exists():
            import shutil
            shutil.rmtree(user_dir)
        
        return True
    
    def list_users(self, admin_username: str) -> list[dict]:
        """
        List all users (admin only)
        
        Args:
            admin_username: Username of the admin requesting the list
            
        Returns:
            List of user dictionaries
            
        Raises:
            AuthenticationError: If admin_username is not an admin
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if requester is admin
        cursor.execute("SELECT is_admin FROM users WHERE username = ?", (admin_username,))
        result = cursor.fetchone()
        if not result or not result[0]:
            conn.close()
            raise AuthenticationError("Only admins can list users")
        
        cursor.execute(
            "SELECT username, is_admin, created_at, last_login FROM users ORDER BY created_at"
        )
        users = []
        for row in cursor.fetchall():
            users.append({
                'username': row[0],
                'is_admin': bool(row[1]),
                'created_at': row[2],
                'last_login': row[3]
            })
        
        conn.close()
        return users
    
    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Change a user's password
        
        Args:
            username: Username whose password to change
            old_password: Current password for verification
            new_password: New password to set
            
        Returns:
            True if password changed successfully
            
        Raises:
            AuthenticationError: If old password is incorrect
            ValueError: If new password is invalid
        """
        if not new_password or len(new_password) < 6:
            raise ValueError("New password must be at least 6 characters long")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            raise ValueError(f"User '{username}' does not exist")
        
        if not self._verify_password(old_password, result[0]):
            conn.close()
            raise AuthenticationError("Incorrect current password")
        
        new_hash = self._hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (new_hash, username)
        )
        
        # Invalidate all existing sessions for this user
        cursor.execute("DELETE FROM sessions WHERE username = ?", (username,))
        
        conn.commit()
        conn.close()
        
        return True
    
    def get_user_dir(self, username: str) -> Path:
        """Get the data directory for a specific user"""
        return Path(f"data/users/{username}")
    
    def get_registration_enabled(self) -> bool:
        """
        Check if user registration is enabled
        
        Returns:
            True if registration is enabled, False otherwise (default: False)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM app_config WHERE key = 'allow_registration'")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0].lower() == 'true'
        return False  # Default to disabled for security
    
    def set_registration_enabled(self, enabled: bool, admin_username: str) -> bool:
        """
        Enable or disable user registration (admin only)
        
        Args:
            enabled: Whether to enable registration
            admin_username: Username of the admin making the change
            
        Returns:
            True if setting was updated successfully
            
        Raises:
            AuthenticationError: If admin_username is not an admin
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if requester is admin
        cursor.execute("SELECT is_admin FROM users WHERE username = ?", (admin_username,))
        result = cursor.fetchone()
        if not result or not result[0]:
            conn.close()
            raise AuthenticationError("Only admins can change registration settings")
        
        # Update or insert the setting
        value = 'true' if enabled else 'false'
        cursor.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES ('allow_registration', ?)",
            (value,)
        )
        
        conn.commit()
        conn.close()
        return True
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "DELETE FROM sessions WHERE expires_at < ?",
            (datetime.utcnow().isoformat(),)
        )
        
        conn.commit()
        conn.close()
