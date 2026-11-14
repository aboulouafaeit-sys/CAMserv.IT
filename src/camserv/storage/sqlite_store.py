"""
camserv.storage.sqlite_store
============================

Durable, transactional relational persistence for CAMserv using SQLite with
Write-Ahead Logging (WAL) enabled for high-concurrency read/write operations.
Persists cameras, users, event histories, and system configuration across service restarts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.pipeline.interfaces import AlertStatus, Event, EventSeverity
from camserv.security.auth import Role

logger = structlog.get_logger(__name__)


class SQLiteStore:
    """Relational storage manager for durable CAMserv platform metadata."""

    def __init__(self, db_path: Path | str = "data/camserv.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection with WAL mode."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema tables if not present."""
        with self._get_connection() as conn:
            # Cameras table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    fps INTEGER NOT NULL DEFAULT 15,
                    width INTEGER NOT NULL DEFAULT 1920,
                    height INTEGER NOT NULL DEFAULT 1080,
                    privacy_zones TEXT DEFAULT '[]',
                    onvif_profile TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Users table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login TEXT DEFAULT NULL
                );
                """
            )

            # Events table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    camera_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    requires_verification INTEGER NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    verified_by TEXT DEFAULT NULL,
                    description TEXT NOT NULL,
                    supporting_observations TEXT DEFAULT '[]',
                    reasoning_trace TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}'
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_camera_time ON events (camera_id, timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_severity ON events (severity);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events (verification_status);")

            # Privacy Evidence Manifests table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS privacy_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    frame_id INTEGER NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    derivative_sha256 TEXT NOT NULL,
                    masking_method TEXT NOT NULL,
                    masked_regions_count INTEGER NOT NULL,
                    privacy_state TEXT NOT NULL,
                    fail_closed_active INTEGER NOT NULL,
                    is_original_preserved INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priv_manifest_camera_time ON privacy_manifests (camera_id, timestamp_utc);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priv_manifest_orig_hash ON privacy_manifests (original_sha256);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priv_manifest_deriv_hash ON privacy_manifests (derivative_sha256);")

            # Enhancement Evidence Manifests table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS enhancement_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    frame_id INTEGER NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    enhanced_sha256 TEXT NOT NULL,
                    applied_methods TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    contrast_before REAL NOT NULL,
                    contrast_after REAL NOT NULL,
                    contrast_gain REAL NOT NULL,
                    is_original_preserved INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_enh_manifest_camera_time ON enhancement_manifests (camera_id, timestamp_utc);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_enh_manifest_orig_hash ON enhancement_manifests (original_sha256);")

            conn.commit()
        logger.info("sqlite.initialized", path=str(self.db_path))

    # ---------------------------------------------------------------------------
    # Camera CRUD
    # ---------------------------------------------------------------------------

    def upsert_camera(self, camera: dict[str, Any]) -> None:
        """Insert or update a camera configuration."""
        now = datetime.now(timezone.utc).isoformat()
        pz_json = json.dumps(camera.get("privacy_zones", []))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cameras (id, name, url, enabled, fps, width, height, privacy_zones, onvif_profile, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    enabled=excluded.enabled,
                    fps=excluded.fps,
                    width=excluded.width,
                    height=excluded.height,
                    privacy_zones=excluded.privacy_zones,
                    onvif_profile=excluded.onvif_profile,
                    updated_at=excluded.updated_at;
                """,
                (
                    camera["id"],
                    camera["name"],
                    camera["url"],
                    1 if camera.get("enabled", True) else 0,
                    camera.get("fps", 15),
                    camera.get("width", 1920),
                    camera.get("height", 1080),
                    pz_json,
                    camera.get("onvif_profile"),
                    camera.get("created_at", now),
                    now,
                ),
            )
            conn.commit()

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        """Retrieve a camera configuration by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["enabled"] = bool(res["enabled"])
            res["privacy_zones"] = json.loads(res["privacy_zones"]) if res.get("privacy_zones") else []
            return res

    def list_cameras(self) -> list[dict[str, Any]]:
        """List all registered cameras."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM cameras ORDER BY id ASC").fetchall()
            results = []
            for r in rows:
                c = dict(r)
                c["enabled"] = bool(c["enabled"])
                c["privacy_zones"] = json.loads(c["privacy_zones"]) if c.get("privacy_zones") else []
                results.append(c)
            return results

    def delete_camera(self, camera_id: str) -> bool:
        """Delete a camera from the database."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            conn.commit()
            return cur.rowcount > 0

    # ---------------------------------------------------------------------------
    # Event Persistence & Human-in-the-Loop Review
    # ---------------------------------------------------------------------------

    def store_event(self, event: Event) -> None:
        """Persist a security event record."""
        ts_str = event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp)
        obs_json = json.dumps(event.metadata.get("supporting_observations", []))
        reasoning = str(event.metadata.get("reasoning_trace", ""))
        meta_json = json.dumps({k: v for k, v in event.metadata.items() if k not in ("supporting_observations", "reasoning_trace")})
        severity_val = event.severity.value if hasattr(event.severity, "value") else str(event.severity)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    event_id, event_type, severity, confidence, camera_id, timestamp,
                    requires_verification, verification_status, description,
                    supporting_observations, reasoning_trace, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    severity_val,
                    float(event.confidence),
                    event.camera_id,
                    ts_str,
                    1 if event.requires_verification else 0,
                    "pending" if event.requires_verification else "auto_resolved",
                    event.description,
                    obs_json,
                    reasoning,
                    meta_json,
                ),
            )
            conn.commit()

    def verify_event(self, event_id: str, verified_by: str, status: str, notes: str = "") -> bool:
        """Record human verification decision on a security event."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE events
                SET verification_status = ?, verified_by = ?, notes = ?
                WHERE event_id = ?
                """,
                (status, verified_by, notes, event_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def query_events(
        self,
        camera_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query persistent event history."""
        clauses = []
        params = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if status:
            clauses.append("verification_status = ?")
            params.append(status)

        query = "SELECT * FROM events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                ev = dict(r)
                ev["requires_verification"] = bool(ev["requires_verification"])
                ev["supporting_observations"] = json.loads(ev["supporting_observations"]) if ev.get("supporting_observations") else []
                ev["metadata"] = json.loads(ev["metadata"]) if ev.get("metadata") else {}
                results.append(ev)
            return results

    # ---------------------------------------------------------------------------
    # User Management
    # ---------------------------------------------------------------------------

    def upsert_user(self, username: str, password_hash: str, role: Role | str) -> None:
        """Add or update a system user account."""
        now = datetime.now(timezone.utc).isoformat()
        role_val = role.value if hasattr(role, "value") else str(role)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active, created_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash=excluded.password_hash,
                    role=excluded.role;
                """,
                (username, password_hash, role_val, now),
            )
            conn.commit()

    def get_user(self, username: str) -> dict[str, Any] | None:
        """Retrieve user credentials and role."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    # ---------------------------------------------------------------------------
    # Forensic Evidence Manifest Persistence (SEC-03)
    # ---------------------------------------------------------------------------

    def store_privacy_manifest(self, manifest: Any) -> None:
        """Persist a privacy evidence manifest linking original and derivative video frames."""
        now = datetime.now(timezone.utc).isoformat()
        if hasattr(manifest, "to_dict"):
            data = manifest.to_dict()
        elif isinstance(manifest, dict):
            data = manifest
        else:
            data = asdict(manifest)

        meta_json = json.dumps(data.get("metadata", {}))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO privacy_manifests (
                    manifest_id, camera_id, frame_id, timestamp_utc, original_sha256,
                    derivative_sha256, masking_method, masked_regions_count, privacy_state,
                    fail_closed_active, is_original_preserved, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["manifest_id"],
                    data["camera_id"],
                    data["frame_id"],
                    data["timestamp_utc"],
                    data["original_sha256"],
                    data["derivative_sha256"],
                    data["masking_method"],
                    data["masked_regions_count"],
                    data["privacy_state"] if isinstance(data["privacy_state"], str) else data["privacy_state"].value,
                    1 if data.get("fail_closed_active") else 0,
                    1 if data.get("is_original_preserved", True) else 0,
                    meta_json,
                    now,
                ),
            )
            conn.commit()

    def get_privacy_manifest(self, manifest_id: str) -> dict[str, Any] | None:
        """Retrieve a privacy manifest by its unique manifest ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM privacy_manifests WHERE manifest_id = ?", (manifest_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["fail_closed_active"] = bool(res["fail_closed_active"])
            res["is_original_preserved"] = bool(res["is_original_preserved"])
            res["metadata"] = json.loads(res["metadata"]) if res.get("metadata") else {}
            return res

    def get_privacy_manifest_by_original_hash(self, original_sha256: str) -> dict[str, Any] | None:
        """Find the privacy manifest associated with a pristine original evidence frame hash."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM privacy_manifests WHERE original_sha256 = ? ORDER BY timestamp_utc DESC LIMIT 1",
                (original_sha256,),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["fail_closed_active"] = bool(res["fail_closed_active"])
            res["is_original_preserved"] = bool(res["is_original_preserved"])
            res["metadata"] = json.loads(res["metadata"]) if res.get("metadata") else {}
            return res

    def list_privacy_manifests(
        self,
        camera_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query privacy manifests filtered by camera and optional time range."""
        clauses = []
        params: list[Any] = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if start_time:
            clauses.append("timestamp_utc >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("timestamp_utc <= ?")
            params.append(end_time)

        query = "SELECT * FROM privacy_manifests"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                m = dict(r)
                m["fail_closed_active"] = bool(m["fail_closed_active"])
                m["is_original_preserved"] = bool(m["is_original_preserved"])
                m["metadata"] = json.loads(m["metadata"]) if m.get("metadata") else {}
                results.append(m)
            return results

    def store_enhancement_manifest(self, manifest: Any) -> None:
        """Persist a forensic image enhancement manifest."""
        now = datetime.now(timezone.utc).isoformat()
        if hasattr(manifest, "to_dict"):
            data = manifest.to_dict()
        elif isinstance(manifest, dict):
            data = manifest
        else:
            data = asdict(manifest)

        methods_json = json.dumps(data.get("applied_methods", []))
        params_json = json.dumps(data.get("parameters", {}))
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enhancement_manifests (
                    manifest_id, camera_id, frame_id, timestamp_utc, original_sha256,
                    enhanced_sha256, applied_methods, parameters, contrast_before,
                    contrast_after, contrast_gain, is_original_preserved, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["manifest_id"],
                    data["camera_id"],
                    data["frame_id"],
                    data["timestamp_utc"],
                    data["original_sha256"],
                    data["enhanced_sha256"],
                    methods_json,
                    params_json,
                    float(data["contrast_before"]),
                    float(data["contrast_after"]),
                    float(data["contrast_gain"]),
                    1 if data.get("is_original_preserved", True) else 0,
                    now,
                ),
            )
            conn.commit()

    def get_enhancement_manifest(self, manifest_id: str) -> dict[str, Any] | None:
        """Retrieve an enhancement manifest by its unique manifest ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM enhancement_manifests WHERE manifest_id = ?", (manifest_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["applied_methods"] = json.loads(res["applied_methods"]) if res.get("applied_methods") else []
            res["parameters"] = json.loads(res["parameters"]) if res.get("parameters") else {}
            res["is_original_preserved"] = bool(res["is_original_preserved"])
            return res

    def list_enhancement_manifests(
        self,
        camera_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List enhancement manifests filtered by camera ID."""
        query = "SELECT * FROM enhancement_manifests"
        params: list[Any] = []
        if camera_id:
            query += " WHERE camera_id = ?"
            params.append(camera_id)
        query += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                m = dict(r)
                m["applied_methods"] = json.loads(m["applied_methods"]) if m.get("applied_methods") else []
                m["parameters"] = json.loads(m["parameters"]) if m.get("parameters") else {}
                m["is_original_preserved"] = bool(m["is_original_preserved"])
                results.append(m)
            return results

    def verify_manifest_integrity_record(self, manifest_id: str, record_type: str = "privacy") -> bool:
        """Verify that a stored manifest record has well-formed cryptographic hashes and valid metadata."""
        if record_type == "privacy":
            rec = self.get_privacy_manifest(manifest_id)
            if not rec:
                return False
            h_orig = rec.get("original_sha256", "")
            h_deriv = rec.get("derivative_sha256", "")
            return len(h_orig) == 64 and len(h_deriv) == 64 and all(c in "0123456789abcdefABCDEF" for c in h_orig + h_deriv)
        elif record_type == "enhancement":
            rec = self.get_enhancement_manifest(manifest_id)
            if not rec:
                return False
            h_orig = rec.get("original_sha256", "")
            h_enh = rec.get("enhanced_sha256", "")
            return len(h_orig) == 64 and len(h_enh) == 64 and all(c in "0123456789abcdefABCDEF" for c in h_orig + h_enh)
        return False

