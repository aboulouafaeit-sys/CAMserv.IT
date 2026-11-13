"""CAMserv Redis caching layer.

Provides :class:`RedisCache`: an async Redis client wrapper with connection
pooling, key namespacing, TTL expiration, serialization, cache invalidation,
health checking, and graceful degradation when Redis is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import structlog

from camserv.pipeline.interfaces import (
    BoundingBox,
    Detection,
    Event,
    EventSeverity,
    Track,
    TrackState,
)

logger = structlog.get_logger(__name__)

# Check if redis is available
try:
    import redis.asyncio as aioredis
    from redis.asyncio.connection import ConnectionPool
    from redis.exceptions import RedisError

    HAS_REDIS = True
except ImportError:  # pragma: no cover
    HAS_REDIS = False
    aioredis = None  # type: ignore[assignment]
    ConnectionPool = None  # type: ignore[assignment,misc]
    RedisError = Exception  # type: ignore[assignment,misc]


class ModelJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for pipeline dataclasses and datetime objects."""

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, (EventSeverity, TrackState)):
            return o.value
        if isinstance(o, BoundingBox):
            return {"x1": o.x1, "y1": o.y1, "x2": o.x2, "y2": o.y2}
        if is_dataclass(o):
            return asdict(o)
        if hasattr(o, "tolist"):  # numpy array
            return o.tolist()
        return super().default(o)


def _serialize(obj: Any) -> str:
    """Serialize object to JSON string."""
    return json.dumps(obj, cls=ModelJSONEncoder)


def _deserialize(payload: str | bytes) -> Any:
    """Deserialize JSON payload."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)


class RedisCache:
    """Async Redis caching layer with key namespacing and fallback degradation.

    When Redis is offline or fails, RedisCache degrades gracefully to an
    in-memory cache or no-op so that the caller never crashes.

    Namespace conventions:
        - `camserv:detections:<camera_id>:<timestamp_ms>`
        - `camserv:tracks:<camera_id>:<track_id>`
        - `camserv:events:<event_id>`
        - `camserv:state:<component>`
    """

    DEFAULT_TTL_DETECTIONS = 300  # 5 minutes
    DEFAULT_TTL_TRACKS = 600  # 10 minutes
    DEFAULT_TTL_EVENTS = 86400  # 24 hours
    DEFAULT_TTL_STATE = 3600  # 1 hour

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        ssl: bool = False,
        max_connections: int = 20,
        socket_timeout: float = 5.0,
        namespace_prefix: str = "camserv",
        enable_fallback: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.ssl = ssl
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.prefix = namespace_prefix
        self.enable_fallback = enable_fallback

        self._pool: Any | None = None
        self._client: Any | None = None
        self._is_connected = False
        self._lock = asyncio.Lock()

        # In-memory fallback dictionary with (data, expiry_timestamp)
        self._memory_store: dict[str, tuple[str, float]] = {}

    def _make_key(self, namespace: str, key: str | int) -> str:
        """Create a namespaced key e.g. camserv:detections:cam1."""
        return f"{self.prefix}:{namespace}:{key}"

    async def connect(self) -> bool:
        """Establish Redis connection pool. Returns True if connected."""
        if not HAS_REDIS:
            logger.warning("redis.unavailable", reason="redis library not installed")
            self._is_connected = False
            return False

        async with self._lock:
            if self._client is not None and self._is_connected:
                return True
            try:
                self._pool = ConnectionPool(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    ssl=self.ssl,
                    max_connections=self.max_connections,
                    socket_timeout=self.socket_timeout,
                    decode_responses=True,
                )
                self._client = aioredis.Redis(connection_pool=self._pool)
                await self._client.ping()
                self._is_connected = True
                logger.info("redis.connected", host=self.host, port=self.port, db=self.db)
                return True
            except (RedisError, OSError, Exception) as exc:
                logger.warning(
                    "redis.connection_failed",
                    host=self.host,
                    port=self.port,
                    error=str(exc),
                    fallback="in-memory" if self.enable_fallback else "none",
                )
                self._is_connected = False
                return False

    async def close(self) -> None:
        """Close Redis connection and pool."""
        async with self._lock:
            if self._client:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
                self._client = None
            if self._pool:
                try:
                    await self._pool.disconnect()
                except Exception:
                    pass
                self._pool = None
            self._is_connected = False
            self._memory_store.clear()
            logger.info("redis.closed")

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        if not self._is_connected or self._client is None:
            # Try to connect once
            return await self.connect()
        try:
            res = await self._client.ping()
            return bool(res)
        except Exception as exc:
            logger.warning("redis.health_check_failed", error=str(exc))
            self._is_connected = False
            return False

    # ---------------------------------------------------------------------------
    # Low-level Get / Set with Fallback
    # ---------------------------------------------------------------------------

    async def set(
        self,
        namespace: str,
        key: str | int,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Store serialized value under namespace:key with optional TTL."""
        full_key = self._make_key(namespace, key)
        serialized = _serialize(value)

        if self._is_connected and self._client is not None:
            try:
                if ttl_seconds is not None and ttl_seconds > 0:
                    await self._client.set(full_key, serialized, ex=ttl_seconds)
                else:
                    await self._client.set(full_key, serialized)
                return True
            except Exception as exc:
                logger.warning("redis.set_failed", key=full_key, error=str(exc))
                self._is_connected = False

        if self.enable_fallback:
            expiry = time.time() + (ttl_seconds if ttl_seconds is not None else 86400 * 365)
            self._memory_store[full_key] = (serialized, expiry)
            self._purge_expired_memory()
            return True

        return False

    async def get(self, namespace: str, key: str | int) -> Any | None:
        """Retrieve and deserialize value from namespace:key."""
        full_key = self._make_key(namespace, key)

        if self._is_connected and self._client is not None:
            try:
                val = await self._client.get(full_key)
                if val is not None:
                    return _deserialize(val)
                return None
            except Exception as exc:
                logger.warning("redis.get_failed", key=full_key, error=str(exc))
                self._is_connected = False

        if self.enable_fallback:
            self._purge_expired_memory()
            entry = self._memory_store.get(full_key)
            if entry is not None:
                data, expiry = entry
                if time.time() < expiry:
                    return _deserialize(data)
                del self._memory_store[full_key]
        return None

    async def delete(self, namespace: str, key: str | int) -> bool:
        """Delete a key."""
        full_key = self._make_key(namespace, key)
        success = True

        if self._is_connected and self._client is not None:
            try:
                await self._client.delete(full_key)
            except Exception as exc:
                logger.warning("redis.delete_failed", key=full_key, error=str(exc))
                self._is_connected = False
                success = False

        if self.enable_fallback and full_key in self._memory_store:
            del self._memory_store[full_key]

        return success

    def _purge_expired_memory(self) -> None:
        """Prune expired in-memory cache entries."""
        now = time.time()
        expired = [k for k, (_, exp) in self._memory_store.items() if now >= exp]
        for k in expired:
            self._memory_store.pop(k, None)

    # ---------------------------------------------------------------------------
    # High-level domain methods
    # ---------------------------------------------------------------------------

    async def cache_detections(
        self,
        camera_id: str,
        detections: Sequence[Detection],
        ttl_seconds: int = DEFAULT_TTL_DETECTIONS,
    ) -> None:
        """Cache a list of recent detections for a camera."""
        timestamp_ms = int(time.time() * 1000)
        key = f"{camera_id}:{timestamp_ms}"
        data = [_detection_to_dict(d) for d in detections]
        await self.set("detections", key, data, ttl_seconds=ttl_seconds)

    async def get_recent_detections(
        self,
        camera_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent detections for a camera."""
        pattern = self._make_key("detections", f"{camera_id}:*")
        keys = await self._find_keys(pattern)
        # sort descending by timestamp key
        keys.sort(reverse=True)
        results: list[dict[str, Any]] = []

        for k in keys[:limit]:
            # k is full key, extract subkey
            sub_key = k[len(f"{self.prefix}:detections:") :]
            val = await self.get("detections", sub_key)
            if val and isinstance(val, list):
                results.extend(val)
                if len(results) >= limit:
                    break
        return results[:limit]

    async def cache_track(
        self,
        track: Track,
        ttl_seconds: int = DEFAULT_TTL_TRACKS,
    ) -> None:
        """Cache active track state."""
        key = f"{track.camera_id}:{track.track_id}"
        data = _track_to_dict(track)
        await self.set("tracks", key, data, ttl_seconds=ttl_seconds)

    async def get_active_tracks(
        self,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get active tracks, optionally filtered by camera."""
        pat = f"{camera_id}:*" if camera_id else "*"
        pattern = self._make_key("tracks", pat)
        keys = await self._find_keys(pattern)
        tracks: list[dict[str, Any]] = []

        for k in keys:
            sub_key = k[len(f"{self.prefix}:tracks:") :]
            val = await self.get("tracks", sub_key)
            if val and isinstance(val, dict):
                tracks.append(val)
        return tracks

    async def cache_event(
        self,
        event: Event,
        ttl_seconds: int = DEFAULT_TTL_EVENTS,
    ) -> None:
        """Cache an event record."""
        key = event.event_id
        data = _event_to_dict(event)
        await self.set("events", key, data, ttl_seconds=ttl_seconds)

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        """Retrieve an event by ID."""
        val = await self.get("events", event_id)
        if isinstance(val, dict):
            return val
        return None

    async def set_system_state(
        self,
        component: str,
        state: dict[str, Any],
        ttl_seconds: int = DEFAULT_TTL_STATE,
    ) -> None:
        """Store component health / state."""
        await self.set("state", component, state, ttl_seconds=ttl_seconds)

    async def get_system_state(self, component: str) -> dict[str, Any] | None:
        """Retrieve component health / state."""
        val = await self.get("state", component)
        if isinstance(val, dict):
            return val
        return None

    # ---------------------------------------------------------------------------
    # Invalidation Strategies
    # ---------------------------------------------------------------------------

    async def invalidate_camera(self, camera_id: str) -> int:
        """Invalidate all cached detections and tracks for a camera."""
        det_keys = await self._find_keys(self._make_key("detections", f"{camera_id}:*"))
        track_keys = await self._find_keys(self._make_key("tracks", f"{camera_id}:*"))
        all_keys = det_keys + track_keys
        count = 0

        for k in all_keys:
            if self._is_connected and self._client is not None:
                try:
                    await self._client.delete(k)
                    count += 1
                except Exception:
                    pass
            if self.enable_fallback and k in self._memory_store:
                del self._memory_store[k]
                count += 1

        logger.info("redis.invalidated_camera", camera_id=camera_id, removed_keys=count)
        return count

    async def invalidate_namespace(self, namespace: str) -> int:
        """Invalidate all keys under a given namespace (e.g. 'detections')."""
        pattern = self._make_key(namespace, "*")
        keys = await self._find_keys(pattern)
        count = 0
        for k in keys:
            if self._is_connected and self._client is not None:
                try:
                    await self._client.delete(k)
                    count += 1
                except Exception:
                    pass
            if self.enable_fallback and k in self._memory_store:
                del self._memory_store[k]
                count += 1
        return count

    async def _find_keys(self, pattern: str) -> list[str]:
        """Find keys matching wildcard pattern across Redis and in-memory store."""
        matching: set[str] = set()

        if self._is_connected and self._client is not None:
            try:
                # Use SCAN for safe key iteration
                cur = b"0" if hasattr(self._client, "scan") else 0
                cursor = 0
                while True:
                    cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=100)
                    for k in keys:
                        matching.add(k if isinstance(k, str) else k.decode())
                    if cursor == 0:
                        break
            except Exception as exc:
                logger.warning("redis.scan_failed", pattern=pattern, error=str(exc))
                self._is_connected = False

        if self.enable_fallback:
            self._purge_expired_memory()
            import fnmatch

            for k in self._memory_store.keys():
                if fnmatch.fnmatch(k, pattern):
                    matching.add(k)

        return list(matching)


# ---------------------------------------------------------------------------
# Conversion Helpers
# ---------------------------------------------------------------------------

def _detection_to_dict(d: Detection) -> dict[str, Any]:
    return {
        "bbox": {
            "x1": d.bbox.x1,
            "y1": d.bbox.y1,
            "x2": d.bbox.x2,
            "y2": d.bbox.y2,
        },
        "class_id": d.class_id,
        "class_name": d.class_name,
        "confidence": float(d.confidence),
        "camera_id": d.camera_id,
        "frame_id": d.frame_id,
        "timestamp": d.timestamp.isoformat() if isinstance(d.timestamp, datetime) else str(d.timestamp),
        "is_prediction": d.is_prediction,
        "metadata": d.metadata,
    }


def _track_to_dict(t: Track) -> dict[str, Any]:
    return {
        "track_id": t.track_id,
        "bbox": {
            "x1": t.bbox.x1,
            "y1": t.bbox.y1,
            "x2": t.bbox.x2,
            "y2": t.bbox.y2,
        },
        "class_name": t.class_name,
        "class_id": t.class_id,
        "confidence": float(t.confidence),
        "age": t.age,
        "state": t.state.value if isinstance(t.state, TrackState) else str(t.state),
        "camera_id": t.camera_id,
        "velocity": list(t.velocity),
        "trajectory": [list(pt) for pt in t.trajectory],
        "last_seen": t.last_seen.isoformat() if t.last_seen else None,
        "metadata": t.metadata,
    }


def _event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "event_id": e.event_id,
        "event_type": e.event_type,
        "severity": e.severity.value if isinstance(e.severity, EventSeverity) else str(e.severity),
        "confidence": float(e.confidence),
        "camera_id": e.camera_id,
        "timestamp": e.timestamp.isoformat() if isinstance(e.timestamp, datetime) else str(e.timestamp),
        "requires_verification": e.requires_verification,
        "description": e.description,
        "related_track_ids": list(e.related_track_ids),
        "related_detections": [_detection_to_dict(d) for d in e.related_detections],
        "zone_id": e.zone_id,
        "is_prediction": e.is_prediction,
        "metadata": e.metadata,
    }
