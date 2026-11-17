"""
camserv.security.identity.store
===============================

Transactional, durable SQLite WAL-backed identity store for CAMserv Local-First Zero-Trust
Identity, Authentication, Authorization & Account Protection.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.security.identity.models import (
    AccountStatus,
    AuthAssuranceLevel,
    IdentityRole,
    MFAType,
    ResourceScope,
    ResourceType,
    SecurityEvent,
    SecurityEventSeverity,
    SessionRecord,
    UserRecord,
)

logger = structlog.get_logger(__name__)

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT,
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    mfa_type TEXT NOT NULL DEFAULT 'none',
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    last_login_utc TEXT,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until_utc TEXT,
    is_administrator INTEGER NOT NULL DEFAULT 0,
    requires_password_change INTEGER NOT NULL DEFAULT 0,
    allowed_camera_ids TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS password_credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    previous_hashes TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS totp_credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    encrypted_secret TEXT NOT NULL,
    digits INTEGER NOT NULL DEFAULT 6,
    interval_sec INTEGER NOT NULL DEFAULT 30,
    algorithm TEXT NOT NULL DEFAULT 'SHA1',
    created_at_utc TEXT NOT NULL,
    last_used_step INTEGER NOT NULL DEFAULT -1
);

CREATE TABLE IF NOT EXISTS recovery_codes (
    code_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    is_used INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    used_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_recovery_codes_user ON recovery_codes(user_id);

CREATE TABLE IF NOT EXISTS passkey_credentials (
    credential_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    public_key TEXT NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    transports TEXT NOT NULL DEFAULT '[]',
    created_at_utc TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    auth_assurance_level TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    last_activity_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
    user_agent TEXT NOT NULL DEFAULT 'local_client',
    is_revoked INTEGER NOT NULL DEFAULT 0,
    revocation_reason TEXT,
    step_up_confirmed_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_revoked, expires_at_utc);

CREATE TABLE IF NOT EXISTS resource_scopes (
    scope_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    permissions TEXT NOT NULL DEFAULT '[]',
    granted_by TEXT NOT NULL,
    granted_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scopes_user ON resource_scopes(user_id);
CREATE INDEX IF NOT EXISTS idx_scopes_lookup ON resource_scopes(user_id, resource_type, resource_id);

CREATE TABLE IF NOT EXISTS security_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    actor_id TEXT,
    ip_address TEXT,
    resource_type TEXT,
    resource_id TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    action_taken TEXT NOT NULL DEFAULT 'LOGGED',
    prev_hash TEXT,
    entry_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_sec_events_time ON security_events(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type);

CREATE TABLE IF NOT EXISTS bootstrap_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);
"""


class DurableIdentityStore:
    """Thread-safe, durable SQLite WAL-backed identity and authorization store."""

    def __init__(self, db_path: str | Path = "data/identity.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # autocommit mode, transactions handled explicitly
        )
        self._conn.row_factory = sqlite3.Row
        try:
            self._init_schema()
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            raise

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------------------------------------------------
    # User Management
    # -------------------------------------------------------------------------

    def create_user(self, user: UserRecord, password_hash: str | None = None) -> UserRecord:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            allowed_cams = json.dumps(list(user.allowed_camera_ids))
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO users (
                        user_id, username, role, status, full_name, email,
                        mfa_enabled, mfa_type, created_at_utc, updated_at_utc,
                        last_login_utc, failed_login_count, locked_until_utc,
                        is_administrator, requires_password_change, allowed_camera_ids
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.username,
                        user.role.value,
                        user.status.value,
                        user.full_name,
                        user.email,
                        1 if user.mfa_enabled else 0,
                        user.mfa_type.value,
                        user.created_at_utc or now,
                        now,
                        user.last_login_utc,
                        user.failed_login_count,
                        user.locked_until_utc,
                        1 if user.is_administrator else 0,
                        1 if user.requires_password_change else 0,
                        allowed_cams,
                    ),
                )
                if password_hash:
                    self._conn.execute(
                        """
                        INSERT INTO password_credentials (
                            user_id, password_hash, created_at_utc, updated_at_utc, previous_hashes
                        ) VALUES (?, ?, ?, ?, '[]')
                        """,
                        (user.user_id, password_hash, now, now),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return user

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    def update_user(self, user: UserRecord) -> UserRecord:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            allowed_cams = json.dumps(list(user.allowed_camera_ids))
            self._conn.execute(
                """
                UPDATE users SET
                    username = ?,
                    role = ?,
                    status = ?,
                    full_name = ?,
                    email = ?,
                    mfa_enabled = ?,
                    mfa_type = ?,
                    updated_at_utc = ?,
                    last_login_utc = ?,
                    failed_login_count = ?,
                    locked_until_utc = ?,
                    is_administrator = ?,
                    requires_password_change = ?,
                    allowed_camera_ids = ?
                WHERE user_id = ?
                """,
                (
                    user.username,
                    user.role.value,
                    user.status.value,
                    user.full_name,
                    user.email,
                    1 if user.mfa_enabled else 0,
                    user.mfa_type.value,
                    now,
                    user.last_login_utc,
                    user.failed_login_count,
                    user.locked_until_utc,
                    1 if user.is_administrator else 0,
                    1 if user.requires_password_change else 0,
                    allowed_cams,
                    user.user_id,
                ),
            )
            return user

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0

    def list_users(self, role: IdentityRole | None = None) -> list[UserRecord]:
        with self._lock:
            if role:
                cursor = self._conn.execute("SELECT * FROM users WHERE role = ? ORDER BY username ASC", (role.value,))
            else:
                cursor = self._conn.execute("SELECT * FROM users ORDER BY username ASC")
            return [self._row_to_user(r) for r in cursor.fetchall()]

    def count_administrators(self) -> int:
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM users WHERE is_administrator = 1 AND status != 'deactivated'")
            return cursor.fetchone()[0]

    def _row_to_user(self, row: sqlite3.Row) -> UserRecord:
        try:
            allowed_cams = set(json.loads(row["allowed_camera_ids"]))
        except Exception:
            allowed_cams = set()

        return UserRecord(
            user_id=row["user_id"],
            username=row["username"],
            role=IdentityRole(row["role"]),
            status=AccountStatus(row["status"]),
            full_name=row["full_name"],
            email=row["email"],
            mfa_enabled=bool(row["mfa_enabled"]),
            mfa_type=MFAType(row["mfa_type"]),
            created_at_utc=row["created_at_utc"],
            updated_at_utc=row["updated_at_utc"],
            last_login_utc=row["last_login_utc"],
            failed_login_count=row["failed_login_count"],
            locked_until_utc=row["locked_until_utc"],
            is_administrator=bool(row["is_administrator"]),
            requires_password_change=bool(row["requires_password_change"]),
            allowed_camera_ids=allowed_cams,
        )

    # -------------------------------------------------------------------------
    # Password Credentials & History
    # -------------------------------------------------------------------------

    def set_password(self, user_id: str, password_hash: str, max_history: int = 5) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            cursor = self._conn.execute("SELECT password_hash, previous_hashes FROM password_credentials WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                old_hash = row["password_hash"]
                try:
                    history = json.loads(row["previous_hashes"])
                except Exception:
                    history = []
                history.append(old_hash)
                if len(history) > max_history:
                    history = history[-max_history:]
                self._conn.execute(
                    """
                    UPDATE password_credentials SET
                        password_hash = ?,
                        updated_at_utc = ?,
                        previous_hashes = ?
                    WHERE user_id = ?
                    """,
                    (password_hash, now, json.dumps(history), user_id),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO password_credentials (
                        user_id, password_hash, created_at_utc, updated_at_utc, previous_hashes
                    ) VALUES (?, ?, ?, ?, '[]')
                    """,
                    (user_id, password_hash, now, now),
                )

    def get_password_hash(self, user_id: str) -> str | None:
        with self._lock:
            cursor = self._conn.execute("SELECT password_hash FROM password_credentials WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row["password_hash"] if row else None

    def record_login_success(self, user_id: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                """
                UPDATE users SET
                    failed_login_count = 0,
                    locked_until_utc = NULL,
                    last_login_utc = ?,
                    status = CASE WHEN status = 'locked' THEN 'active' ELSE status END
                WHERE user_id = ?
                """,
                (now, user_id),
            )

    def record_login_failure(
        self,
        user_id: str,
        lockout_duration_sec: float = 300.0,
        max_attempts: int = 5,
    ) -> tuple[int, bool]:
        """Increment failed login count. Lock account if threshold exceeded.

        Returns (new_failed_count, is_locked).
        """
        with self._lock:
            cursor = self._conn.execute("SELECT failed_login_count FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return (0, False)

            new_count = row["failed_login_count"] + 1
            locked = False
            locked_until = None

            if new_count >= max_attempts:
                locked = True
                lockout_end = datetime.now(timezone.utc) + timedelta(seconds=lockout_duration_sec)
                locked_until = lockout_end.isoformat()
                self._conn.execute(
                    """
                    UPDATE users SET
                        failed_login_count = ?,
                        locked_until_utc = ?,
                        status = 'locked'
                    WHERE user_id = ?
                    """,
                    (new_count, locked_until, user_id),
                )
            else:
                self._conn.execute(
                    "UPDATE users SET failed_login_count = ? WHERE user_id = ?",
                    (new_count, user_id),
                )

            return (new_count, locked)

    # -------------------------------------------------------------------------
    # TOTP Credentials & Recovery Codes
    # -------------------------------------------------------------------------

    def set_totp_credential(
        self,
        user_id: str,
        encrypted_secret: str,
        digits: int = 6,
        interval_sec: int = 30,
        algorithm: str = "SHA1",
    ) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                """
                INSERT OR REPLACE INTO totp_credentials (
                    user_id, encrypted_secret, digits, interval_sec, algorithm, created_at_utc, last_used_step
                ) VALUES (?, ?, ?, ?, ?, ?, -1)
                """,
                (user_id, encrypted_secret, digits, interval_sec, algorithm, now),
            )
            self._conn.execute(
                "UPDATE users SET mfa_enabled = 1, mfa_type = 'totp' WHERE user_id = ?",
                (user_id,),
            )

    def get_totp_credential(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM totp_credentials WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "user_id": row["user_id"],
                "encrypted_secret": row["encrypted_secret"],
                "digits": row["digits"],
                "interval_sec": row["interval_sec"],
                "algorithm": row["algorithm"],
                "created_at_utc": row["created_at_utc"],
                "last_used_step": row["last_used_step"],
            }

    def update_totp_last_step(self, user_id: str, step: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE totp_credentials SET last_used_step = ? WHERE user_id = ?",
                (step, user_id),
            )

    def clear_totp_credential(self, user_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM totp_credentials WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
            self._conn.execute(
                "UPDATE users SET mfa_enabled = 0, mfa_type = 'none' WHERE user_id = ?",
                (user_id,),
            )

    def store_recovery_codes(self, user_id: str, code_hashes: list[str]) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
                for ch in code_hashes:
                    cid = hashlib.sha256(f"{user_id}:{ch}".encode()).hexdigest()[:16]
                    self._conn.execute(
                        """
                        INSERT INTO recovery_codes (code_id, user_id, code_hash, is_used, created_at_utc)
                        VALUES (?, ?, ?, 0, ?)
                        """,
                        (cid, user_id, ch, now),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def verify_and_consume_recovery_code(self, user_id: str, code_hash: str) -> bool:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            cursor = self._conn.execute(
                "SELECT code_id FROM recovery_codes WHERE user_id = ? AND code_hash = ? AND is_used = 0",
                (user_id, code_hash),
            )
            row = cursor.fetchone()
            if not row:
                return False
            self._conn.execute(
                "UPDATE recovery_codes SET is_used = 1, used_at_utc = ? WHERE code_id = ?",
                (now, row["code_id"]),
            )
            return True

    def get_available_recovery_code_count(self, user_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM recovery_codes WHERE user_id = ? AND is_used = 0",
                (user_id,),
            )
            return cursor.fetchone()[0]

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def create_session(self, session: SessionRecord) -> SessionRecord:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, user_id, username, role, auth_assurance_level,
                    created_at_utc, last_activity_utc, expires_at_utc,
                    ip_address, user_agent, is_revoked, revocation_reason,
                    step_up_confirmed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.user_id,
                    session.username,
                    session.role.value,
                    session.auth_assurance_level.value,
                    session.created_at_utc,
                    session.last_activity_utc,
                    session.expires_at_utc,
                    session.ip_address,
                    session.user_agent,
                    1 if session.is_revoked else 0,
                    session.revocation_reason,
                    session.step_up_confirmed_at_utc,
                ),
            )
            return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_session(row)

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "UPDATE sessions SET last_activity_utc = ? WHERE session_id = ? AND is_revoked = 0",
                (now, session_id),
            )

    def revoke_session(self, session_id: str, reason: str = "manual_revocation") -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET is_revoked = 1, revocation_reason = ? WHERE session_id = ?",
                (reason, session_id),
            )
            return cursor.rowcount > 0

    def revoke_all_user_sessions(self, user_id: str, reason: str = "user_revocation") -> int:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET is_revoked = 1, revocation_reason = ? WHERE user_id = ? AND is_revoked = 0",
                (reason, user_id),
            )
            return cursor.rowcount

    def list_active_sessions_for_user(self, user_id: str) -> list[SessionRecord]:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            cursor = self._conn.execute(
                """
                SELECT * FROM sessions
                WHERE user_id = ? AND is_revoked = 0 AND expires_at_utc > ?
                ORDER BY created_at_utc DESC
                """,
                (user_id, now),
            )
            return [self._row_to_session(r) for r in cursor.fetchall()]

    def _row_to_session(self, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            user_id=row["user_id"],
            username=row["username"],
            role=IdentityRole(row["role"]),
            auth_assurance_level=AuthAssuranceLevel(row["auth_assurance_level"]),
            created_at_utc=row["created_at_utc"],
            last_activity_utc=row["last_activity_utc"],
            expires_at_utc=row["expires_at_utc"],
            ip_address=row["ip_address"],
            user_agent=row["user_agent"],
            is_revoked=bool(row["is_revoked"]),
            revocation_reason=row["revocation_reason"],
            step_up_confirmed_at_utc=row["step_up_confirmed_at_utc"],
        )

    # -------------------------------------------------------------------------
    # Resource Scopes (Object-Level Authorization)
    # -------------------------------------------------------------------------

    def add_resource_scope(self, scope: ResourceScope) -> ResourceScope:
        with self._lock:
            perms_json = json.dumps(list(scope.permissions))
            self._conn.execute(
                """
                INSERT OR REPLACE INTO resource_scopes (
                    scope_id, user_id, resource_type, resource_id, permissions, granted_by, granted_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope.scope_id,
                    scope.user_id,
                    scope.resource_type.value,
                    scope.resource_id,
                    perms_json,
                    scope.granted_by,
                    scope.granted_at_utc,
                ),
            )
            return scope

    def remove_resource_scope(self, scope_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM resource_scopes WHERE scope_id = ?", (scope_id,))
            return cursor.rowcount > 0

    def get_user_resource_scopes(
        self,
        user_id: str,
        resource_type: ResourceType | None = None,
    ) -> list[ResourceScope]:
        with self._lock:
            if resource_type:
                cursor = self._conn.execute(
                    "SELECT * FROM resource_scopes WHERE user_id = ? AND resource_type = ?",
                    (user_id, resource_type.value),
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM resource_scopes WHERE user_id = ?",
                    (user_id,),
                )
            results: list[ResourceScope] = []
            for r in cursor.fetchall():
                try:
                    perms = set(json.loads(r["permissions"]))
                except Exception:
                    perms = set()
                results.append(
                    ResourceScope(
                        scope_id=r["scope_id"],
                        user_id=r["user_id"],
                        resource_type=ResourceType(r["resource_type"]),
                        resource_id=r["resource_id"],
                        permissions=perms,
                        granted_by=r["granted_by"],
                        granted_at_utc=r["granted_at_utc"],
                    )
                )
            return results

    def has_resource_permission(
        self,
        user_id: str,
        resource_type: ResourceType,
        resource_id: str,
        permission: str,
    ) -> bool:
        """Check if user has explicit permission on resource_id or wildcard '*'."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT permissions FROM resource_scopes
                WHERE user_id = ? AND resource_type = ? AND (resource_id = ? OR resource_id = '*')
                """,
                (user_id, resource_type.value, resource_id),
            )
            for r in cursor.fetchall():
                try:
                    perms = set(json.loads(r["permissions"]))
                    if "*" in perms or permission in perms:
                        return True
                    # Check domain wildcard e.g. "camera:*"
                    domain = permission.split(":")[0] + ":*"
                    if domain in perms:
                        return True
                except Exception:
                    pass
            return False

    # -------------------------------------------------------------------------
    # Security Events (Audit with Cryptographic Hash Chaining)
    # -------------------------------------------------------------------------

    def record_security_event(self, event: SecurityEvent) -> SecurityEvent:
        with self._lock:
            cursor = self._conn.execute("SELECT entry_hash FROM security_events ORDER BY rowid DESC LIMIT 1")
            last_row = cursor.fetchone()
            prev_hash = last_row["entry_hash"] if last_row and last_row["entry_hash"] else "GENESIS_SECURITY_AUDIT_HASH_PHASE26_00000000"

            details_json = json.dumps(event.details, sort_keys=True)
            payload = f"{event.event_id}:{event.event_type}:{event.severity.value}:{event.timestamp_utc}:{event.actor_id}:{event.ip_address}:{event.resource_type}:{event.resource_id}:{details_json}:{event.action_taken}:{prev_hash}"
            entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

            self._conn.execute(
                """
                INSERT INTO security_events (
                    event_id, event_type, severity, timestamp_utc,
                    actor_id, ip_address, resource_type, resource_id,
                    details, action_taken, prev_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.severity.value,
                    event.timestamp_utc,
                    event.actor_id,
                    event.ip_address,
                    event.resource_type,
                    event.resource_id,
                    details_json,
                    event.action_taken,
                    prev_hash,
                    entry_hash,
                ),
            )
            return event

    def list_security_events(
        self,
        limit: int = 100,
        severity: SecurityEventSeverity | None = None,
    ) -> list[SecurityEvent]:
        with self._lock:
            if severity:
                cursor = self._conn.execute(
                    "SELECT * FROM security_events WHERE severity = ? ORDER BY rowid DESC LIMIT ?",
                    (severity.value, limit),
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM security_events ORDER BY rowid DESC LIMIT ?",
                    (limit,),
                )
            events: list[SecurityEvent] = []
            for r in cursor.fetchall():
                try:
                    dt = json.loads(r["details"])
                except Exception:
                    dt = {}
                events.append(
                    SecurityEvent(
                        event_id=r["event_id"],
                        event_type=r["event_type"],
                        severity=SecurityEventSeverity(r["severity"]),
                        timestamp_utc=r["timestamp_utc"],
                        actor_id=r["actor_id"],
                        ip_address=r["ip_address"],
                        resource_type=r["resource_type"],
                        resource_id=r["resource_id"],
                        details=dt,
                        action_taken=r["action_taken"],
                    )
                )
            return events

    # -------------------------------------------------------------------------
    # Bootstrap State
    # -------------------------------------------------------------------------

    def is_bootstrapped(self) -> bool:
        with self._lock:
            cursor = self._conn.execute("SELECT value FROM bootstrap_state WHERE key = 'is_bootstrapped'")
            row = cursor.fetchone()
            return row is not None and row["value"] == "1"

    def set_bootstrapped(self, admin_id: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT OR REPLACE INTO bootstrap_state (key, value, updated_at_utc) VALUES ('is_bootstrapped', '1', ?)",
                (now,),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO bootstrap_state (key, value, updated_at_utc) VALUES ('bootstrap_admin_id', ?, ?)",
                (admin_id, now),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO bootstrap_state (key, value, updated_at_utc) VALUES ('bootstrap_completed_at', ?, ?)",
                (now, now),
            )

    def store_bootstrap_token(self, token_hash: str, expires_at_utc: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT OR REPLACE INTO bootstrap_state (key, value, updated_at_utc) VALUES ('bootstrap_token_hash', ?, ?)",
                (token_hash, now),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO bootstrap_state (key, value, updated_at_utc) VALUES ('bootstrap_token_expires', ?, ?)",
                (expires_at_utc, now),
            )

    def get_bootstrap_token(self) -> dict[str, str] | None:
        with self._lock:
            c1 = self._conn.execute("SELECT value FROM bootstrap_state WHERE key = 'bootstrap_token_hash'")
            r1 = c1.fetchone()
            c2 = self._conn.execute("SELECT value FROM bootstrap_state WHERE key = 'bootstrap_token_expires'")
            r2 = c2.fetchone()
            if not r1 or not r2:
                return None
            return {"token_hash": r1["value"], "expires_at_utc": r2["value"]}

    def invalidate_bootstrap_token(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM bootstrap_state WHERE key IN ('bootstrap_token_hash', 'bootstrap_token_expires')")
