"""
database.py - SQLite Database Module for Cloud Security gRPC Simulator

This module provides:
- Database connection management
- Schema creation (users, otps tables)
- User CRUD operations
- OTP storage and verification

Usage:
    from database import Database
    db = Database()
    db.create_user("johndoe", "john@example.com", "hashed_password")
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from contextlib import contextmanager

from params import DATABASE_PATH, OTP_EXPIRY_MINUTES, MAX_LOGIN_ATTEMPTS, LOCKOUT_DURATION_MINUTES

# Set up logger for this module
logger = logging.getLogger(__name__)


class Database:
    """
    SQLite database manager for the Cloud Security application.

    Handles all database operations including user management and OTP storage.
    """

    def __init__(self, db_path: str = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Defaults to DATABASE_PATH from params.
        """
        self.db_path = db_path or DATABASE_PATH
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """
        Context manager for database connections.

        Ensures connections are properly closed after use.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    failed_login_attempts INTEGER DEFAULT 0,
                    locked_until TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # OTPs table (for login, signup verification, password reset)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS otps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    otp_code TEXT NOT NULL,
                    otp_type TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    is_used INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            # Login attempts table (for rate limiting and security audit)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT NOT NULL,
                    ip_address TEXT,
                    success INTEGER DEFAULT 0,
                    failure_reason TEXT,
                    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                )
            ''')

            # Sessions table (for tracking active sessions)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_id TEXT NOT NULL UNIQUE,
                    device_info TEXT,
                    ip_address TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_revoked INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            # Audit logs table (for tracking all security events)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    user_id INTEGER,
                    username TEXT,
                    details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    success INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                )
            ''')

            # =========================================================================
            # Storage System Tables
            # =========================================================================

            # Storage files table (replaces JSON file registry)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS storage_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT UNIQUE NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    checksum TEXT,
                    owner_id INTEGER,
                    status TEXT DEFAULT 'available',
                    replication_factor INTEGER DEFAULT 2,
                    target_replicas INTEGER DEFAULT 2,
                    upload_time REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
                )
            ''')

            # Storage file nodes (which nodes have which files)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS storage_file_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    is_primary INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (file_id) REFERENCES storage_files(file_id) ON DELETE CASCADE,
                    UNIQUE(file_id, node_id)
                )
            ''')

            # Storage nodes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS storage_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT UNIQUE NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    status TEXT DEFAULT 'offline',
                    cpu_capacity INTEGER DEFAULT 0,
                    memory_capacity INTEGER DEFAULT 0,
                    storage_capacity INTEGER DEFAULT 0,
                    bandwidth INTEGER DEFAULT 0,
                    last_heartbeat TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # User storage quotas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_storage_quotas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    quota_bytes INTEGER DEFAULT 1073741824,
                    used_bytes INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            # Create indexes for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_otps_user_id ON otps(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_otps_code ON otps(otp_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_user_id ON login_attempts(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_username ON login_attempts(username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_token_id ON sessions(token_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs(event_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at)')
            # Storage indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_storage_files_file_id ON storage_files(file_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_storage_files_owner_id ON storage_files(owner_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_storage_file_nodes_file_id ON storage_file_nodes(file_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_storage_file_nodes_node_id ON storage_file_nodes(node_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_storage_nodes_node_id ON storage_nodes(node_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_storage_quotas_user_id ON user_storage_quotas(user_id)')

            logger.info(f"Database initialized: {self.db_path}")

    # =========================================================================
    # User Operations
    # =========================================================================

    def create_user(self, username: str, email: str, password_hash: str,
                    is_verified: bool = False) -> Optional[int]:
        """
        Create a new user in the database.

        Args:
            username: Unique username
            email: Unique email address
            password_hash: bcrypt hashed password
            is_verified: Whether email is verified (default False for signup flow)

        Returns:
            User ID if created successfully, None if user exists
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO users (username, email, password_hash, is_verified)
                    VALUES (?, ?, ?, ?)
                ''', (username, email, password_hash, int(is_verified)))
                user_id = cursor.lastrowid
                logger.info(f"Created user: {username} (ID: {user_id})")
                return user_id
        except sqlite3.IntegrityError as e:
            logger.warning(f"User creation failed (duplicate): {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """
        Get user by username.

        Args:
            username: Username to look up

        Returns:
            User dict with all fields, or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """
        Get user by email.

        Args:
            email: Email address to look up

        Returns:
            User dict with all fields, or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        """Get user by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_user(self, user_id: int, **kwargs) -> bool:
        """
        Update user fields.

        Args:
            user_id: User ID to update
            **kwargs: Fields to update (email, password_hash, is_verified, is_active)

        Returns:
            True if updated, False if user not found
        """
        allowed_fields = {'email', 'password_hash', 'is_verified', 'is_active'}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not updates:
            return False

        updates['updated_at'] = datetime.now().isoformat()

        set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [user_id]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE users SET {set_clause} WHERE id = ?', values)
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Updated user ID {user_id}: {list(updates.keys())}")
            return updated

    def delete_user(self, user_id: int) -> bool:
        """
        Delete a user from the database.

        Args:
            user_id: User ID to delete

        Returns:
            True if deleted, False if user not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted user ID {user_id}")
            return deleted

    def verify_user_email(self, user_id: int) -> bool:
        """Mark user's email as verified."""
        return self.update_user(user_id, is_verified=True)

    def increment_failed_login(self, user_id: int) -> int:
        """
        Increment failed login attempts and lock account if threshold reached.

        Uses MAX_LOGIN_ATTEMPTS and LOCKOUT_DURATION_MINUTES from params.

        Returns:
            Current failed attempt count
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET failed_login_attempts = failed_login_attempts + 1,
                    updated_at = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), user_id))

            cursor.execute('SELECT failed_login_attempts FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            count = row[0] if row else 0

            # Lock account after MAX_LOGIN_ATTEMPTS for LOCKOUT_DURATION_MINUTES
            if count >= MAX_LOGIN_ATTEMPTS:
                lock_until = datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                cursor.execute('''
                    UPDATE users SET locked_until = ? WHERE id = ?
                ''', (lock_until.isoformat(), user_id))
                logger.warning(f"Account locked for user ID {user_id} until {lock_until} ({LOCKOUT_DURATION_MINUTES} min)")

            return count

    def reset_failed_login(self, user_id: int) -> None:
        """Reset failed login attempts after successful login."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET failed_login_attempts = 0, locked_until = NULL, updated_at = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), user_id))

    def is_account_locked(self, user_id: int) -> Tuple[bool, Optional[datetime]]:
        """
        Check if account is currently locked.

        Returns:
            Tuple of (is_locked, locked_until_datetime)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT locked_until FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            if row and row[0]:
                locked_until = datetime.fromisoformat(row[0])
                if datetime.now() < locked_until:
                    return True, locked_until
                # Lock expired, reset it
                self.reset_failed_login(user_id)
            return False, None

    # =========================================================================
    # OTP Operations
    # =========================================================================

    def create_otp(self, user_id: int, otp_code: str, otp_type: str = 'login') -> int:
        """
        Store a new OTP for a user.

        Args:
            user_id: User ID the OTP belongs to
            otp_code: The 6-digit OTP code
            otp_type: Type of OTP ('login', 'signup', 'reset')

        Returns:
            OTP record ID
        """
        expires_at = datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Invalidate any existing unused OTPs of the same type for this user
            cursor.execute('''
                UPDATE otps SET is_used = 1
                WHERE user_id = ? AND otp_type = ? AND is_used = 0
            ''', (user_id, otp_type))

            # Create new OTP
            cursor.execute('''
                INSERT INTO otps (user_id, otp_code, otp_type, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, otp_code, otp_type, expires_at.isoformat()))

            otp_id = cursor.lastrowid
            logger.debug(f"Created OTP for user ID {user_id}, type: {otp_type}, expires: {expires_at}")
            return otp_id

    def verify_otp(self, user_id: int, otp_code: str, otp_type: str = 'login') -> bool:
        """
        Verify an OTP code for a user.

        Args:
            user_id: User ID to verify OTP for
            otp_code: The OTP code to verify
            otp_type: Type of OTP ('login', 'signup', 'reset')

        Returns:
            True if OTP is valid, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Find valid OTP
            cursor.execute('''
                SELECT id, expires_at FROM otps
                WHERE user_id = ? AND otp_code = ? AND otp_type = ? AND is_used = 0
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id, otp_code, otp_type))

            row = cursor.fetchone()
            if not row:
                logger.warning(f"OTP verification failed: No matching OTP for user ID {user_id}")
                return False

            otp_id, expires_at = row[0], row[1]

            # Check expiry
            if datetime.now() > datetime.fromisoformat(expires_at):
                logger.warning(f"OTP verification failed: Expired OTP for user ID {user_id}")
                return False

            # Mark OTP as used
            cursor.execute('UPDATE otps SET is_used = 1 WHERE id = ?', (otp_id,))
            logger.info(f"OTP verified successfully for user ID {user_id}")
            return True

    def cleanup_expired_otps(self) -> int:
        """
        Remove expired OTPs from the database.

        Returns:
            Number of OTPs deleted
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM otps
                WHERE expires_at < ? OR is_used = 1
            ''', (datetime.now().isoformat(),))
            deleted = cursor.rowcount
            if deleted > 0:
                logger.debug(f"Cleaned up {deleted} expired/used OTPs")
            return deleted

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_all_users(self) -> List[dict]:
        """Get all users (for admin/debugging purposes)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, username, email, is_verified, is_active, created_at FROM users')
            return [dict(row) for row in cursor.fetchall()]

    def user_exists(self, username: str = None, email: str = None) -> bool:
        """Check if a user exists by username or email."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if username:
                cursor.execute('SELECT 1 FROM users WHERE username = ?', (username,))
            elif email:
                cursor.execute('SELECT 1 FROM users WHERE email = ?', (email,))
            else:
                return False
            return cursor.fetchone() is not None

    # =========================================================================
    # Rate Limiting & Account Lockout Operations
    # =========================================================================

    def record_login_attempt(self, username: str, user_id: int = None,
                             ip_address: str = None, success: bool = False,
                             failure_reason: str = None) -> None:
        """
        Record a login attempt for security auditing.

        Args:
            username: The username attempted
            user_id: The user's ID (if found)
            ip_address: Client IP address
            success: Whether login was successful
            failure_reason: Reason for failure (if failed)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO login_attempts
                (user_id, username, ip_address, success, failure_reason)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, ip_address, 1 if success else 0, failure_reason))

        logger.info(f"Login attempt recorded: {username} - {'SUCCESS' if success else 'FAILED'}")

    def increment_failed_attempts(self, user_id: int, max_attempts: int,
                                   lockout_minutes: int) -> Tuple[int, bool]:
        """
        Increment failed login attempts and check if account should be locked.

        Args:
            user_id: The user's ID
            max_attempts: Maximum allowed failed attempts
            lockout_minutes: How long to lock the account

        Returns:
            Tuple of (current_attempts, is_now_locked)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Increment failed attempts
            cursor.execute('''
                UPDATE users
                SET failed_login_attempts = failed_login_attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (user_id,))

            # Get current attempts
            cursor.execute('SELECT failed_login_attempts FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            current_attempts = row['failed_login_attempts'] if row else 0

            # Lock account if max attempts reached
            is_locked = False
            if current_attempts >= max_attempts:
                locked_until = datetime.now() + timedelta(minutes=lockout_minutes)
                cursor.execute('''
                    UPDATE users
                    SET locked_until = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (locked_until.isoformat(), user_id))
                is_locked = True
                logger.warning(f"Account locked for user_id={user_id} until {locked_until}")

            return current_attempts, is_locked

    def reset_failed_attempts(self, user_id: int) -> None:
        """
        Reset failed login attempts on successful login.

        Args:
            user_id: The user's ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET failed_login_attempts = 0,
                    locked_until = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (user_id,))

        logger.info(f"Failed attempts reset for user_id={user_id}")

    def is_account_locked(self, user_id: int) -> Tuple[bool, Optional[datetime]]:
        """
        Check if an account is currently locked.

        Args:
            user_id: The user's ID

        Returns:
            Tuple of (is_locked, locked_until_datetime)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT locked_until, failed_login_attempts
                FROM users WHERE id = ?
            ''', (user_id,))
            row = cursor.fetchone()

            if not row or not row['locked_until']:
                return False, None

            locked_until_str = row['locked_until']
            try:
                locked_until = datetime.fromisoformat(locked_until_str)
                if datetime.now() < locked_until:
                    return True, locked_until
                else:
                    # Lock expired, reset it
                    cursor.execute('''
                        UPDATE users
                        SET locked_until = NULL,
                            failed_login_attempts = 0,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (user_id,))
                    return False, None
            except (ValueError, TypeError):
                return False, None

    def get_recent_failed_attempts(self, username: str = None, ip_address: str = None,
                                    minutes: int = 15) -> int:
        """
        Get count of recent failed login attempts.

        Args:
            username: Filter by username
            ip_address: Filter by IP address
            minutes: Time window to check (default 15 minutes)

        Returns:
            Number of failed attempts in the time window
        """
        cutoff = datetime.now() - timedelta(minutes=minutes)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            if username:
                cursor.execute('''
                    SELECT COUNT(*) as count FROM login_attempts
                    WHERE username = ? AND success = 0 AND attempted_at > ?
                ''', (username, cutoff.isoformat()))
            elif ip_address:
                cursor.execute('''
                    SELECT COUNT(*) as count FROM login_attempts
                    WHERE ip_address = ? AND success = 0 AND attempted_at > ?
                ''', (ip_address, cutoff.isoformat()))
            else:
                return 0

            row = cursor.fetchone()
            return row['count'] if row else 0

    def get_login_history(self, user_id: int = None, username: str = None,
                          limit: int = 10) -> List[dict]:
        """
        Get login history for a user.

        Args:
            user_id: Filter by user ID
            username: Filter by username
            limit: Maximum records to return

        Returns:
            List of login attempt records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if user_id:
                cursor.execute('''
                    SELECT * FROM login_attempts
                    WHERE user_id = ?
                    ORDER BY attempted_at DESC LIMIT ?
                ''', (user_id, limit))
            elif username:
                cursor.execute('''
                    SELECT * FROM login_attempts
                    WHERE username = ?
                    ORDER BY attempted_at DESC LIMIT ?
                ''', (username, limit))
            else:
                cursor.execute('''
                    SELECT * FROM login_attempts
                    ORDER BY attempted_at DESC LIMIT ?
                ''', (limit,))

            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Session Operations
    # =========================================================================

    def create_session(self, user_id: int, token_id: str, expires_at: datetime,
                       device_info: str = None, ip_address: str = None) -> int:
        """
        Create a new session for a user.

        Args:
            user_id: The user's ID
            token_id: Unique identifier for the JWT (jti claim)
            expires_at: When the session/token expires
            device_info: Optional device/browser info
            ip_address: Optional IP address

        Returns:
            The session ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sessions (user_id, token_id, device_info, ip_address, expires_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, token_id, device_info, ip_address, expires_at.isoformat()))
            session_id = cursor.lastrowid
            logger.info(f"Session created for user ID {user_id}, session ID {session_id}")
            return session_id

    def get_active_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Get all active (non-revoked, non-expired) sessions for a user.

        Args:
            user_id: The user's ID

        Returns:
            List of active session dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, token_id, device_info, ip_address, created_at, expires_at, last_activity
                FROM sessions
                WHERE user_id = ? AND is_revoked = 0 AND expires_at > ?
                ORDER BY last_activity DESC
            ''', (user_id, datetime.now().isoformat()))
            return [dict(row) for row in cursor.fetchall()]

    def get_session_by_token_id(self, token_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a session by its token ID.

        Args:
            token_id: The JWT token ID (jti claim)

        Returns:
            Session dictionary or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM sessions WHERE token_id = ?
            ''', (token_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def is_session_valid(self, token_id: str) -> bool:
        """
        Check if a session is valid (exists, not revoked, not expired).

        Args:
            token_id: The JWT token ID (jti claim)

        Returns:
            True if session is valid, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM sessions
                WHERE token_id = ? AND is_revoked = 0 AND expires_at > ?
            ''', (token_id, datetime.now().isoformat()))
            return cursor.fetchone() is not None

    def update_session_activity(self, token_id: str) -> bool:
        """
        Update the last_activity timestamp for a session.

        Args:
            token_id: The JWT token ID (jti claim)

        Returns:
            True if updated, False if session not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sessions SET last_activity = ?
                WHERE token_id = ? AND is_revoked = 0
            ''', (datetime.now().isoformat(), token_id))
            return cursor.rowcount > 0

    def revoke_session(self, token_id: str) -> bool:
        """
        Revoke a specific session by token ID.

        Args:
            token_id: The JWT token ID (jti claim)

        Returns:
            True if session was revoked, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sessions SET is_revoked = 1
                WHERE token_id = ?
            ''', (token_id,))
            if cursor.rowcount > 0:
                logger.info(f"Session revoked: {token_id}")
                return True
            return False

    def revoke_all_sessions(self, user_id: int, except_token_id: str = None) -> int:
        """
        Revoke all sessions for a user (logout from all devices).

        Args:
            user_id: The user's ID
            except_token_id: Optional token ID to keep active (current session)

        Returns:
            Number of sessions revoked
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if except_token_id:
                cursor.execute('''
                    UPDATE sessions SET is_revoked = 1
                    WHERE user_id = ? AND token_id != ? AND is_revoked = 0
                ''', (user_id, except_token_id))
            else:
                cursor.execute('''
                    UPDATE sessions SET is_revoked = 1
                    WHERE user_id = ? AND is_revoked = 0
                ''', (user_id,))
            count = cursor.rowcount
            logger.info(f"Revoked {count} sessions for user ID {user_id}")
            return count

    def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions from database.

        Returns:
            Number of sessions removed
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM sessions WHERE expires_at < ?
            ''', (datetime.now().isoformat(),))
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Cleaned up {count} expired sessions")
            return count

    def get_session_count(self, user_id: int) -> int:
        """
        Get count of active sessions for a user.

        Args:
            user_id: The user's ID

        Returns:
            Number of active sessions
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM sessions
                WHERE user_id = ? AND is_revoked = 0 AND expires_at > ?
            ''', (user_id, datetime.now().isoformat()))
            return cursor.fetchone()[0]

    # =========================================================================
    # Audit Logging Methods
    # =========================================================================

    def log_event(
        self,
        event_type: str,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True
    ) -> int:
        """
        Log an audit event.

        Args:
            event_type: Type of event (LOGIN, LOGOUT, SIGNUP, PASSWORD_RESET, etc.)
            user_id: User's ID (optional)
            username: Username (optional)
            details: Additional details about the event
            ip_address: IP address of the request
            user_agent: User agent string
            success: Whether the action was successful

        Returns:
            The ID of the created log entry
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO audit_logs
                (event_type, user_id, username, details, ip_address, user_agent, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (event_type, user_id, username, details, ip_address, user_agent, 1 if success else 0))
            conn.commit()
            log_id = cursor.lastrowid
            logger.debug(f"Audit log created: {event_type} for user {username or user_id}")
            return log_id

    def get_user_logs(
        self,
        user_id: int,
        limit: int = 50,
        event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get audit logs for a specific user.

        Args:
            user_id: User's ID
            limit: Maximum number of logs to return
            event_type: Filter by event type (optional)

        Returns:
            List of audit log entries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if event_type:
                cursor.execute('''
                    SELECT id, event_type, user_id, username, details, ip_address,
                           user_agent, success, created_at
                    FROM audit_logs
                    WHERE user_id = ? AND event_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (user_id, event_type, limit))
            else:
                cursor.execute('''
                    SELECT id, event_type, user_id, username, details, ip_address,
                           user_agent, success, created_at
                    FROM audit_logs
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (user_id, limit))

            rows = cursor.fetchall()
            return [
                {
                    'id': row[0],
                    'event_type': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'details': row[4],
                    'ip_address': row[5],
                    'user_agent': row[6],
                    'success': bool(row[7]),
                    'created_at': row[8]
                }
                for row in rows
            ]

    def get_all_logs(
        self,
        limit: int = 100,
        event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all audit logs (admin function).

        Args:
            limit: Maximum number of logs to return
            event_type: Filter by event type (optional)

        Returns:
            List of audit log entries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if event_type:
                cursor.execute('''
                    SELECT id, event_type, user_id, username, details, ip_address,
                           user_agent, success, created_at
                    FROM audit_logs
                    WHERE event_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (event_type, limit))
            else:
                cursor.execute('''
                    SELECT id, event_type, user_id, username, details, ip_address,
                           user_agent, success, created_at
                    FROM audit_logs
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))

            rows = cursor.fetchall()
            return [
                {
                    'id': row[0],
                    'event_type': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'details': row[4],
                    'ip_address': row[5],
                    'user_agent': row[6],
                    'success': bool(row[7]),
                    'created_at': row[8]
                }
                for row in rows
            ]

    def get_event_types(self) -> List[str]:
        """
        Get all unique event types in the audit log.

        Returns:
            List of event type strings
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT event_type FROM audit_logs ORDER BY event_type')
            return [row[0] for row in cursor.fetchall()]

    # =========================================================================
    # Storage File Operations
    # =========================================================================

    def create_storage_file(self, file_id: str, file_name: str, file_size: int,
                            checksum: str = None, owner_id: int = None,
                            replication_factor: int = 2, target_replicas: int = 2,
                            upload_time: float = None) -> bool:
        """Create a new storage file record."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO storage_files
                    (file_id, file_name, file_size, checksum, owner_id,
                     replication_factor, target_replicas, upload_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (file_id, file_name, file_size, checksum, owner_id,
                      replication_factor, target_replicas, upload_time))
                logger.info(f"Created storage file: {file_name} ({file_id})")
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"Storage file already exists: {file_id}")
            return False

    def get_storage_file(self, file_id: str) -> Optional[Dict]:
        """Get storage file by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT file_id, file_name, file_size, checksum, owner_id, status,
                       replication_factor, target_replicas, upload_time, created_at
                FROM storage_files WHERE file_id = ?
            ''', (file_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'file_id': row[0], 'file_name': row[1], 'file_size': row[2],
                    'checksum': row[3], 'owner_id': row[4], 'status': row[5],
                    'replication_factor': row[6], 'target_replicas': row[7],
                    'upload_time': row[8], 'created_at': row[9]
                }
            return None

    def get_storage_file_by_name(self, file_name: str, owner_id: int = None) -> Optional[Dict]:
        """Get storage file by name, optionally filtered by owner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if owner_id:
                cursor.execute('''
                    SELECT file_id, file_name, file_size, checksum, owner_id, status,
                           replication_factor, target_replicas, upload_time, created_at
                    FROM storage_files WHERE file_name = ? AND owner_id = ?
                ''', (file_name, owner_id))
            else:
                cursor.execute('''
                    SELECT file_id, file_name, file_size, checksum, owner_id, status,
                           replication_factor, target_replicas, upload_time, created_at
                    FROM storage_files WHERE file_name = ?
                ''', (file_name,))
            row = cursor.fetchone()
            if row:
                return {
                    'file_id': row[0], 'file_name': row[1], 'file_size': row[2],
                    'checksum': row[3], 'owner_id': row[4], 'status': row[5],
                    'replication_factor': row[6], 'target_replicas': row[7],
                    'upload_time': row[8], 'created_at': row[9]
                }
            return None

    def list_storage_files(self, owner_id: int = None) -> List[Dict]:
        """List all storage files, optionally filtered by owner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if owner_id:
                cursor.execute('''
                    SELECT file_id, file_name, file_size, checksum, owner_id, status,
                           replication_factor, target_replicas, upload_time, created_at
                    FROM storage_files WHERE owner_id = ? ORDER BY created_at DESC
                ''', (owner_id,))
            else:
                cursor.execute('''
                    SELECT file_id, file_name, file_size, checksum, owner_id, status,
                           replication_factor, target_replicas, upload_time, created_at
                    FROM storage_files ORDER BY created_at DESC
                ''')
            return [
                {
                    'file_id': row[0], 'file_name': row[1], 'file_size': row[2],
                    'checksum': row[3], 'owner_id': row[4], 'status': row[5],
                    'replication_factor': row[6], 'target_replicas': row[7],
                    'upload_time': row[8], 'created_at': row[9]
                }
                for row in cursor.fetchall()
            ]

    def update_storage_file_status(self, file_id: str, status: str) -> bool:
        """Update storage file status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE storage_files SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE file_id = ?
            ''', (status, file_id))
            return cursor.rowcount > 0

    def delete_storage_file(self, file_id: str) -> bool:
        """Delete a storage file record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM storage_files WHERE file_id = ?', (file_id,))
            return cursor.rowcount > 0

    # =========================================================================
    # Storage File Node Operations
    # =========================================================================

    def add_file_to_node(self, file_id: str, node_id: str, is_primary: bool = False) -> bool:
        """Add a file-node association."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO storage_file_nodes (file_id, node_id, is_primary)
                    VALUES (?, ?, ?)
                ''', (file_id, node_id, 1 if is_primary else 0))
                return True
        except Exception as e:
            logger.error(f"Error adding file to node: {e}")
            return False

    def remove_file_from_node(self, file_id: str, node_id: str) -> bool:
        """Remove a file-node association."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM storage_file_nodes WHERE file_id = ? AND node_id = ?
            ''', (file_id, node_id))
            return cursor.rowcount > 0

    def get_file_nodes(self, file_id: str) -> Dict[str, List[str]]:
        """Get all nodes that have a file."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT node_id, is_primary FROM storage_file_nodes WHERE file_id = ?
            ''', (file_id,))
            primary_nodes = []
            replica_nodes = []
            for row in cursor.fetchall():
                if row[1]:
                    primary_nodes.append(row[0])
                else:
                    replica_nodes.append(row[0])
            return {'primary_nodes': primary_nodes, 'replica_nodes': replica_nodes}

    def get_node_files(self, node_id: str) -> List[str]:
        """Get all files on a node."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT file_id FROM storage_file_nodes WHERE node_id = ?
            ''', (node_id,))
            return [row[0] for row in cursor.fetchall()]

    # =========================================================================
    # Storage Node Operations
    # =========================================================================

    def register_storage_node(self, node_id: str, host: str, port: int,
                              cpu_capacity: int = 0, memory_capacity: int = 0,
                              storage_capacity: int = 0, bandwidth: int = 0) -> bool:
        """Register or update a storage node."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO storage_nodes
                    (node_id, host, port, status, cpu_capacity, memory_capacity,
                     storage_capacity, bandwidth, last_heartbeat)
                    VALUES (?, ?, ?, 'active', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(node_id) DO UPDATE SET
                        host = excluded.host,
                        port = excluded.port,
                        status = 'active',
                        cpu_capacity = excluded.cpu_capacity,
                        memory_capacity = excluded.memory_capacity,
                        storage_capacity = excluded.storage_capacity,
                        bandwidth = excluded.bandwidth,
                        last_heartbeat = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                ''', (node_id, host, port, cpu_capacity, memory_capacity,
                      storage_capacity, bandwidth))
                logger.info(f"Registered storage node: {node_id}")
                return True
        except Exception as e:
            logger.error(f"Error registering storage node: {e}")
            return False

    def update_node_status(self, node_id: str, status: str) -> bool:
        """Update storage node status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE storage_nodes SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE node_id = ?
            ''', (status, node_id))
            return cursor.rowcount > 0

    def update_node_heartbeat(self, node_id: str) -> bool:
        """Update node heartbeat timestamp."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE storage_nodes SET last_heartbeat = CURRENT_TIMESTAMP
                WHERE node_id = ?
            ''', (node_id,))
            return cursor.rowcount > 0

    def get_storage_node(self, node_id: str) -> Optional[Dict]:
        """Get storage node by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT node_id, host, port, status, cpu_capacity, memory_capacity,
                       storage_capacity, bandwidth, last_heartbeat
                FROM storage_nodes WHERE node_id = ?
            ''', (node_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'node_id': row[0], 'host': row[1], 'port': row[2],
                    'status': row[3], 'cpu_capacity': row[4], 'memory_capacity': row[5],
                    'storage_capacity': row[6], 'bandwidth': row[7], 'last_heartbeat': row[8]
                }
            return None

    def list_storage_nodes(self, status: str = None) -> List[Dict]:
        """List all storage nodes, optionally filtered by status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute('''
                    SELECT node_id, host, port, status, cpu_capacity, memory_capacity,
                           storage_capacity, bandwidth, last_heartbeat
                    FROM storage_nodes WHERE status = ?
                ''', (status,))
            else:
                cursor.execute('''
                    SELECT node_id, host, port, status, cpu_capacity, memory_capacity,
                           storage_capacity, bandwidth, last_heartbeat
                    FROM storage_nodes
                ''')
            return [
                {
                    'node_id': row[0], 'host': row[1], 'port': row[2],
                    'status': row[3], 'cpu_capacity': row[4], 'memory_capacity': row[5],
                    'storage_capacity': row[6], 'bandwidth': row[7], 'last_heartbeat': row[8]
                }
                for row in cursor.fetchall()
            ]

    # =========================================================================
    # User Storage Quota Operations
    # =========================================================================

    def get_user_quota(self, user_id: int) -> Dict:
        """Get user storage quota. Creates default quota if not exists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT quota_bytes, used_bytes FROM user_storage_quotas WHERE user_id = ?
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                return {'quota_bytes': row[0], 'used_bytes': row[1],
                        'available_bytes': row[0] - row[1]}
            # Create default quota (1GB)
            default_quota = 1073741824  # 1GB in bytes
            cursor.execute('''
                INSERT INTO user_storage_quotas (user_id, quota_bytes, used_bytes)
                VALUES (?, ?, 0)
            ''', (user_id, default_quota))
            return {'quota_bytes': default_quota, 'used_bytes': 0,
                    'available_bytes': default_quota}

    def update_user_used_storage(self, user_id: int, bytes_delta: int) -> bool:
        """Update user's used storage by delta (positive for add, negative for remove)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Ensure quota record exists
            self.get_user_quota(user_id)
            cursor.execute('''
                UPDATE user_storage_quotas
                SET used_bytes = MAX(0, used_bytes + ?), updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (bytes_delta, user_id))
            return cursor.rowcount > 0

    def set_user_quota(self, user_id: int, quota_bytes: int) -> bool:
        """Set user's storage quota."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_storage_quotas (user_id, quota_bytes, used_bytes)
                VALUES (?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    quota_bytes = excluded.quota_bytes,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, quota_bytes))
            return True

    def check_quota_available(self, user_id: int, file_size: int) -> Tuple[bool, int]:
        """Check if user has enough quota for a file. Returns (has_space, available_bytes)."""
        quota = self.get_user_quota(user_id)
        available = quota['available_bytes']
        return (available >= file_size, available)


# =============================================================================
# Module-level convenience functions
# =============================================================================
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Get or create the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

