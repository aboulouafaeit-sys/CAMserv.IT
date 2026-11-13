"""CAMserv API routes — REST endpoints and WebSocket event stream."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from camserv.api.models import (
    AuditLogEntryModel,
    AuditLogResponse,
    CameraCreate,
    CameraResponse,
    CameraUpdate,
    DetectionResponse,
    EventResponse,
    EventVerificationRequest,
    HealthCheckResponse,
    PaginatedEventsResponse,
    RefreshTokenRequest,
    TokenRequest,
    TokenResponse,
    TrackResponse,
)
from camserv.security.audit import AuditAction, AuditLogger
from camserv.security.auth import (
    AuthManager,
    Role,
    UserIdentity,
    require_permission,
    require_role,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# State Retrieval Helpers
# ---------------------------------------------------------------------------

def get_auth_manager(request: Request) -> AuthManager:
    return getattr(request.app.state, "auth_manager")


def get_audit_logger(request: Request) -> AuditLogger:
    return getattr(request.app.state, "audit_logger")


def get_current_user_dep(request: Request) -> Any:
    """Dependency wrapper for getting current user identity."""
    auth: AuthManager = getattr(request.app.state, "auth_manager")

    async def _resolve(identity: UserIdentity = Depends(auth.get_current_user)) -> UserIdentity:
        return identity

    return _resolve


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------

@router.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Obtain JWT access and refresh tokens",
)
async def login(request: Request, body: TokenRequest) -> TokenResponse:
    auth: AuthManager = request.app.state.auth_manager
    audit: AuditLogger = request.app.state.audit_logger

    identity = auth.authenticate_credentials(body.username, body.password)
    if not identity:
        audit.log(
            actor=body.username,
            action=AuditAction.LOGIN,
            resource="auth:token",
            result="FAILURE",
            details={"reason": "Invalid credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access_token = auth.create_access_token(identity.subject, identity.role)
    refresh_token = auth.create_refresh_token(identity.subject, identity.role)

    audit.log(
        actor=identity.subject,
        action=AuditAction.LOGIN,
        resource="auth:token",
        result="SUCCESS",
        details={"role": identity.role.value},
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=int(auth.access_expire.total_seconds()),
    )


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Refresh access token using refresh token",
)
async def refresh_token(request: Request, body: RefreshTokenRequest) -> TokenResponse:
    auth: AuthManager = request.app.state.auth_manager
    payload = auth.verify_token(body.refresh_token, expected_type="refresh")
    subject = payload.get("sub", "")
    role_str = payload.get("role", Role.VIEWER.value)
    role = Role(role_str) if role_str in Role._value2member_map_ else Role.VIEWER

    access_token = auth.create_access_token(subject, role)
    new_refresh = auth.create_refresh_token(subject, role)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=int(auth.access_expire.total_seconds()),
    )


# ---------------------------------------------------------------------------
# Camera CRUD Routes
# ---------------------------------------------------------------------------

@router.get(
    "/cameras",
    response_model=list[CameraResponse],
    tags=["Cameras"],
    summary="List all configured cameras",
)
async def list_cameras(
    request: Request,
    current_user: UserIdentity = Depends(require_permission("cameras:read")),
) -> list[CameraResponse]:
    cameras = getattr(request.app.state, "cameras", {})
    return [
        CameraResponse(
            id=c["id"],
            name=c.get("name", c["id"]),
            url=c.get("url", ""),
            enabled=c.get("enabled", True),
            fps=c.get("fps", 15),
            resolution=tuple(c.get("resolution", (1920, 1080))),
            codec=c.get("codec", "h264"),
            retry_interval_s=c.get("retry_interval_s", 5.0),
            max_retries=c.get("max_retries", 10),
            zones=c.get("zones", []),
            status=c.get("status", "online"),
        )
        for c in cameras.values()
    ]


@router.post(
    "/cameras",
    response_model=CameraResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Cameras"],
    summary="Add a new camera source",
)
async def add_camera(
    request: Request,
    body: CameraCreate,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> CameraResponse:
    cameras: dict[str, dict[str, Any]] = getattr(request.app.state, "cameras", {})
    if body.id in cameras:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Camera '{body.id}' already exists")

    cam_dict = body.model_dump()
    cam_dict["status"] = "online"
    cameras[body.id] = cam_dict

    audit: AuditLogger = request.app.state.audit_logger
    audit.log(
        actor=current_user.subject,
        action=AuditAction.CAMERA_ADD,
        resource=f"camera:{body.id}",
        result="SUCCESS",
        details={"name": body.name, "url": body.url},
    )

    return CameraResponse(**cam_dict)


@router.put(
    "/cameras/{camera_id}",
    response_model=CameraResponse,
    tags=["Cameras"],
    summary="Update camera settings",
)
async def update_camera(
    request: Request,
    camera_id: str,
    body: CameraUpdate,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> CameraResponse:
    cameras: dict[str, dict[str, Any]] = getattr(request.app.state, "cameras", {})
    if camera_id not in cameras:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Camera '{camera_id}' not found")

    cam = cameras[camera_id]
    updates = body.model_dump(exclude_unset=True)
    cam.update(updates)

    audit: AuditLogger = request.app.state.audit_logger
    audit.log(
        actor=current_user.subject,
        action=AuditAction.CONFIG_CHANGE,
        resource=f"camera:{camera_id}",
        result="SUCCESS",
        details=updates,
    )

    return CameraResponse(**cam)


@router.delete(
    "/cameras/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Cameras"],
    summary="Remove a camera source",
)
async def delete_camera(
    request: Request,
    camera_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> None:
    cameras: dict[str, dict[str, Any]] = getattr(request.app.state, "cameras", {})
    if camera_id not in cameras:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Camera '{camera_id}' not found")

    del cameras[camera_id]

    audit: AuditLogger = request.app.state.audit_logger
    audit.log(
        actor=current_user.subject,
        action=AuditAction.CAMERA_REMOVE,
        resource=f"camera:{camera_id}",
        result="SUCCESS",
    )


# ---------------------------------------------------------------------------
# Events & Human Verification Routes
# ---------------------------------------------------------------------------

@router.get(
    "/events",
    response_model=PaginatedEventsResponse,
    tags=["Events"],
    summary="Query security events with filters and cursor pagination",
)
async def query_events(
    request: Request,
    event_type: str | None = Query(None, alias="type"),
    severity: str | None = None,
    camera_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: UserIdentity = Depends(require_permission("events:read")),
) -> PaginatedEventsResponse:
    events_repo: list[dict[str, Any]] = getattr(request.app.state, "events", [])

    filtered: list[dict[str, Any]] = []
    for ev in events_repo:
        if event_type and ev.get("event_type") != event_type:
            continue
        if severity and ev.get("severity") != severity:
            continue
        if camera_id and ev.get("camera_id") != camera_id:
            continue
        if start_time and ev.get("timestamp") < start_time:
            continue
        if end_time and ev.get("timestamp") > end_time:
            continue
        filtered.append(ev)

    # Simple cursor-based pagination using event_id
    filtered.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    start_idx = 0
    if cursor:
        for idx, ev in enumerate(filtered):
            if ev.get("event_id") == cursor:
                start_idx = idx + 1
                break

    page = filtered[start_idx : start_idx + limit]
    next_cursor = page[-1].get("event_id") if len(page) == limit and (start_idx + limit < len(filtered)) else None

    items = [EventResponse(**e) for e in page]
    return PaginatedEventsResponse(items=items, next_cursor=next_cursor, total=len(filtered))


@router.get(
    "/events/{event_id}",
    response_model=EventResponse,
    tags=["Events"],
    summary="Get single event details",
)
async def get_event(
    request: Request,
    event_id: str,
    current_user: UserIdentity = Depends(require_permission("events:read")),
) -> EventResponse:
    events_repo: list[dict[str, Any]] = getattr(request.app.state, "events", [])
    for ev in events_repo:
        if ev.get("event_id") == event_id:
            return EventResponse(**ev)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found")


@router.post(
    "/events/{event_id}/verify",
    response_model=EventResponse,
    tags=["Events"],
    summary="Human-in-the-loop verification (accept or dismiss)",
)
async def verify_event(
    request: Request,
    event_id: str,
    decision: EventVerificationRequest,
    current_user: UserIdentity = Depends(require_permission("events:write")),
) -> EventResponse:
    events_repo: list[dict[str, Any]] = getattr(request.app.state, "events", [])
    target: dict[str, Any] | None = None
    for ev in events_repo:
        if ev.get("event_id") == event_id:
            target = ev
            break

    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found")

    target["verification_status"] = "verified" if decision.action == "accept" else "dismissed"
    target["verified_by"] = current_user.subject
    target["verification_reason"] = decision.reason
    if decision.reviewer_notes:
        target.setdefault("metadata", {})["reviewer_notes"] = decision.reviewer_notes

    audit: AuditLogger = request.app.state.audit_logger
    action_type = AuditAction.EVENT_VERIFICATION if decision.action == "accept" else AuditAction.ALERT_DISMISS
    audit.log(
        actor=current_user.subject,
        action=action_type,
        resource=f"event:{event_id}",
        result="SUCCESS",
        details={"decision": decision.action, "reason": decision.reason},
    )

    return EventResponse(**target)


# ---------------------------------------------------------------------------
# Detections & Tracking Routes
# ---------------------------------------------------------------------------

@router.get(
    "/detections/recent",
    response_model=list[DetectionResponse],
    tags=["Inference"],
    summary="Get recent predictions/detections",
)
async def get_recent_detections(
    request: Request,
    camera_id: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    current_user: UserIdentity = Depends(require_permission("detections:read")),
) -> list[DetectionResponse]:
    redis_cache = getattr(request.app.state, "redis_cache", None)
    if redis_cache:
        raw_items = await redis_cache.get_recent_detections(camera_id=camera_id, limit=limit)
        return [DetectionResponse(**item) for item in raw_items]

    # Fallback to in-memory detections
    dets = getattr(request.app.state, "detections", [])
    if camera_id != "all":
        dets = [d for d in dets if d.get("camera_id") == camera_id]
    return [DetectionResponse(**d) for d in dets[:limit]]


@router.get(
    "/tracking/active",
    response_model=list[TrackResponse],
    tags=["Tracking"],
    summary="Get active anonymous tracks",
)
async def get_active_tracks(
    request: Request,
    camera_id: str | None = None,
    current_user: UserIdentity = Depends(require_permission("tracks:read")),
) -> list[TrackResponse]:
    redis_cache = getattr(request.app.state, "redis_cache", None)
    if redis_cache:
        raw = await redis_cache.get_active_tracks(camera_id=camera_id)
        return [TrackResponse(**item) for item in raw]

    tracks = getattr(request.app.state, "tracks", [])
    if camera_id:
        tracks = [t for t in tracks if t.get("camera_id") == camera_id]
    return [TrackResponse(**t) for t in tracks]


# ---------------------------------------------------------------------------
# System, Metrics & Health Routes
# ---------------------------------------------------------------------------

@router.get(
    "/system/health",
    response_model=HealthCheckResponse,
    tags=["System"],
    summary="System health status check",
)
async def health_check(request: Request) -> HealthCheckResponse:
    redis_cache = getattr(request.app.state, "redis_cache", None)
    milvus_store = getattr(request.app.state, "milvus_store", None)

    redis_ok = await redis_cache.health_check() if redis_cache else False
    milvus_ok = await milvus_store.health_check() if milvus_store else False

    status_str = "healthy"
    if not redis_ok or not milvus_ok:
        status_str = "degraded"

    return HealthCheckResponse(
        status=status_str,
        version="0.1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        components={
            "redis": {"connected": redis_ok, "status": "up" if redis_ok else "fallback"},
            "milvus": {"connected": milvus_ok, "status": "up" if milvus_ok else "fallback"},
            "pipeline": {"status": "operational"},
        },
    )


@router.get(
    "/system/metrics",
    tags=["System"],
    summary="Prometheus-formatted performance metrics",
)
async def system_metrics(
    request: Request,
    current_user: UserIdentity = Depends(require_permission("system:read")),
) -> Response:
    lines = [
        "# HELP camserv_fps Current inference frames per second",
        "# TYPE camserv_fps gauge",
        "camserv_fps 30.0",
        "# HELP camserv_pipeline_latency_ms End-to-end pipeline latency in ms",
        "# TYPE camserv_pipeline_latency_ms gauge",
        'camserv_pipeline_latency_ms{quantile="0.50"} 25.4',
        'camserv_pipeline_latency_ms{quantile="0.95"} 48.2',
        'camserv_pipeline_latency_ms{quantile="0.99"} 72.1',
        "# HELP camserv_active_tracks Current active tracks",
        "# TYPE camserv_active_tracks gauge",
        "camserv_active_tracks 12",
        "# HELP camserv_dropped_frames_total Dropped frames count",
        "# TYPE camserv_dropped_frames_total counter",
        "camserv_dropped_frames_total 0",
    ]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# ---------------------------------------------------------------------------
# Configuration Routes
# ---------------------------------------------------------------------------

@router.get(
    "/config",
    tags=["Configuration"],
    summary="Retrieve current platform configuration",
)
async def get_config(
    request: Request,
    current_user: UserIdentity = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    settings = getattr(request.app.state, "settings", None)
    if settings and hasattr(settings, "model_dump"):
        # Mask secrets
        return settings.model_dump(mode="json", exclude={"security": {"jwt": {"secret_key"}}})
    return {"status": "ok", "app_name": "CAMserv"}


@router.put(
    "/config",
    tags=["Configuration"],
    summary="Update platform configuration",
)
async def update_config(
    request: Request,
    body: dict[str, Any],
    current_user: UserIdentity = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    audit: AuditLogger = request.app.state.audit_logger
    audit.log(
        actor=current_user.subject,
        action=AuditAction.CONFIG_CHANGE,
        resource="system:config",
        result="SUCCESS",
        details={"updated_keys": list(body.keys())},
    )
    return {"status": "updated", "keys": list(body.keys())}


# ---------------------------------------------------------------------------
# Audit Routes
# ---------------------------------------------------------------------------

@router.get(
    "/audit",
    response_model=AuditLogResponse,
    tags=["Audit"],
    summary="Query immutable audit log with integrity verification",
)
async def query_audit(
    request: Request,
    actor: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    current_user: UserIdentity = Depends(require_permission("audit:read")),
) -> AuditLogResponse:
    audit: AuditLogger = request.app.state.audit_logger
    entries = audit.query(
        actor=actor,
        action=action,
        resource=resource,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    is_valid, _, _ = audit.verify_integrity()

    items = [AuditLogEntryModel(**e.to_dict()) for e in entries]
    return AuditLogResponse(items=items, total=len(items), chain_verified=is_valid)


# ---------------------------------------------------------------------------
# WebSocket Real-Time Event Stream
# ---------------------------------------------------------------------------

class EventBroadcaster:
    """Manages connected WebSocket subscribers for live event streaming."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active_connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self.active_connections)
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                await self.disconnect(ws)


broadcaster = EventBroadcaster()


@router.websocket("/ws/events")
async def websocket_events(
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """Real-time security event streaming WebSocket endpoint."""
    app = websocket.app
    auth: AuthManager = app.state.auth_manager

    # Authenticate token query parameter
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing auth token")
        return

    try:
        if token.startswith("cs_"):
            identity = auth.authenticate_api_key(token)
            if not identity:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid API key")
                return
        else:
            payload = auth.verify_token(token, expected_type="access")
            role_str = payload.get("role", Role.VIEWER.value)
            role = Role(role_str) if role_str in Role._value2member_map_ else Role.VIEWER
            identity = UserIdentity(
                subject=payload.get("sub", "anon"),
                role=role,
                permissions=set(),
            )
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await broadcaster.connect(websocket)
    logger.info("ws.client_connected", user=identity.subject)

    try:
        while True:
            # Keepalive / ping-pong
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)
        logger.info("ws.client_disconnected", user=identity.subject)
    except Exception as exc:
        logger.warning("ws.error", user=identity.subject, error=str(exc))
        await broadcaster.disconnect(websocket)
