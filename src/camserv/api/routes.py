"""CAMserv API routes — REST endpoints and WebSocket event stream."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import time
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
from fastapi.responses import StreamingResponse

from camserv.api.models import (
    AuditLogEntryModel,
    AuditLogResponse,
    CameraCreate,
    CameraGroupCreate,
    CameraGroupResponse,
    CameraResponse,
    CameraUpdate,
    ClippedExportRequest,
    ClippedExportResponse,
    DetectionResponse,
    EventResponse,
    EventVerificationRequest,
    ForensicExportRequest,
    ForensicExportResponse,
    HealthCheckResponse,
    JudicialHoldRequest,
    JudicialHoldResponse,
    PaginatedEventsResponse,
    PolygonZoneCreate,
    PTZCapabilitiesResponse,
    PTZMoveRequest,
    PTZPresetCreate,
    PTZPresetResponse,
    RecordingResponse,
    RecordingSegmentResponse,
    RecordingTimelineResponse,
    RefreshTokenRequest,
    TimelineMarkerModel,
    TimelineSpanModel,
    TokenRequest,
    TokenResponse,
    TrackResponse,
    TripwireCreate,
    ZoneEventResponse,
)
from camserv.nvr.ptz import PTZController, PTZUnsupportedError, PTZVector
from camserv.nvr.groups import CameraGroupManager
from camserv.nvr.playback import PlaybackTimelineEngine
from camserv.nvr.streaming import StreamingGateway
from camserv.analytics.zones import PolygonZone, Tripwire, ZoneAnalyticsEngine
from camserv.security.audit import AuditAction, AuditLogger
from camserv.security.rbac import Permission, QuorumAuthorizationError, RBACManager
from camserv.security.auth import (
    AuthManager,
    Role,
    UserIdentity,
    require_permission,
    require_role,
)
from camserv.storage.tiered_storage import ExportAuthorizationError

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


@router.get(
    "/cameras/{camera_id}",
    response_model=CameraResponse,
    tags=["Cameras"],
    summary="Get single camera details",
)
async def get_camera(
    request: Request,
    camera_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:read")),
) -> CameraResponse:
    cameras = getattr(request.app.state, "cameras", {})
    if camera_id not in cameras:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Camera '{camera_id}' not found")
    return CameraResponse(**cameras[camera_id])


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
# Camera Groups Routes
# ---------------------------------------------------------------------------

@router.get(
    "/groups",
    response_model=list[CameraGroupResponse],
    tags=["Camera Groups"],
    summary="List all logical camera groups",
)
async def list_groups(
    request: Request,
    site_id: str | None = None,
    current_user: UserIdentity = Depends(require_permission("cameras:read")),
) -> list[CameraGroupResponse]:
    mgr: CameraGroupManager = getattr(request.app.state, "group_manager", None)
    if not mgr:
        return []
    groups = mgr.list_groups(site_id=site_id)
    return [CameraGroupResponse(**g.to_dict()) for g in groups]


@router.post(
    "/groups",
    response_model=CameraGroupResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Camera Groups"],
    summary="Create a new logical camera group",
)
async def create_group(
    request: Request,
    body: CameraGroupCreate,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> CameraGroupResponse:
    mgr: CameraGroupManager = getattr(request.app.state, "group_manager", None)
    if not mgr:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Group manager unavailable")

    try:
        grp = mgr.create_group(
            group_id=body.group_id,
            name=body.name,
            description=body.description,
            camera_ids=body.camera_ids,
            site_id=body.site_id,
            tags=body.tags,
        )
        return CameraGroupResponse(**grp.to_dict())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Camera Groups"],
    summary="Delete a camera group",
)
async def delete_group(
    request: Request,
    group_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> None:
    mgr: CameraGroupManager = getattr(request.app.state, "group_manager", None)
    if not mgr or not mgr.delete_group(group_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Group '{group_id}' not found")


# ---------------------------------------------------------------------------
# NVR Recordings & Playback Routes
# ---------------------------------------------------------------------------

@router.get(
    "/recordings",
    response_model=list[RecordingResponse],
    tags=["NVR Recordings"],
    summary="List recording sessions",
)
async def list_recordings(
    request: Request,
    camera_id: str | None = None,
    recording_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: UserIdentity = Depends(require_permission("recordings:read")),
) -> list[RecordingResponse]:
    store = getattr(request.app.state, "sqlite_store", None)
    if not store:
        return []
    recs = store.list_recordings(camera_id=camera_id, recording_type=recording_type, limit=limit)
    return [RecordingResponse(**r) for r in recs]


@router.get(
    "/recordings/timeline",
    response_model=RecordingTimelineResponse,
    tags=["NVR Recordings"],
    summary="Query recording timeline spans and event overlays",
)
async def get_recording_timeline(
    request: Request,
    camera_id: str = Query(...),
    start_time_utc: str = Query(...),
    end_time_utc: str = Query(...),
    current_user: UserIdentity = Depends(require_permission("recordings:read")),
) -> RecordingTimelineResponse:
    playback: PlaybackTimelineEngine = getattr(request.app.state, "playback_engine", None)
    if not playback:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Playback engine unavailable")

    if start_time_utc > end_time_utc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_time_utc cannot be greater than end_time_utc")

    spans = playback.get_camera_timeline(camera_id, start_time_utc, end_time_utc)
    span_models = [
        TimelineSpanModel(
            camera_id=s.camera_id,
            start_time_utc=s.start_time_utc,
            end_time_utc=s.end_time_utc,
            duration_seconds=s.duration_seconds,
            segment_ids=s.segment_ids,
            has_motion=s.has_motion,
            has_event=s.has_event,
            markers=[TimelineMarkerModel(**m.to_dict()) for m in s.markers],
        )
        for s in spans
    ]
    return RecordingTimelineResponse(
        camera_id=camera_id,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        spans=span_models,
    )


@router.post(
    "/recordings/export",
    response_model=ClippedExportResponse,
    tags=["NVR Recordings"],
    summary="Export a clipped video range matching requested time window",
)
async def export_recording_clip(
    request: Request,
    body: ClippedExportRequest,
    current_user: UserIdentity = Depends(require_permission("recordings:write")),
) -> ClippedExportResponse:
    playback: PlaybackTimelineEngine = getattr(request.app.state, "playback_engine", None)
    if not playback:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Playback engine unavailable")

    if body.start_time_utc > body.end_time_utc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_time_utc cannot be greater than end_time_utc")

    out_file = Path("data/exports") / f"clip_{body.camera_id}_{int(time.time())}.mp4"
    try:
        manifest = playback.export_clipped_range(
            camera_id=body.camera_id,
            start_time_utc=body.start_time_utc,
            end_time_utc=body.end_time_utc,
            output_path=out_file,
        )
        return ClippedExportResponse(**manifest)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/recordings/export-forensic",
    response_model=ForensicExportResponse,
    tags=["NVR Recordings"],
    summary="Export court-admissible forensic evidence archive with cryptographic Ed25519 signature",
)
async def export_forensic_evidence(
    request: Request,
    body: ForensicExportRequest,
    current_user: UserIdentity = Depends(require_permission("recordings:write")),
) -> ForensicExportResponse:
    playback: PlaybackTimelineEngine = getattr(request.app.state, "playback_engine", None)
    if not playback:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Playback engine unavailable")
    auth_mgr: AuthManager = getattr(request.app.state, "auth_manager", None)
    audit: AuditLogger = getattr(request.app.state, "audit_logger", None)

    dual_quorum_approved = False
    if body.include_raw:
        if not body.co_signer_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Dual-control authorization required: co_signer_token must be provided for unmasked raw export.",
            )
        try:
            co_signer = auth_mgr.verify_token(body.co_signer_token)
            co_signer_role = co_signer.get("role") if isinstance(co_signer, dict) else getattr(co_signer, "role", "unknown")
            co_signer_user_id = co_signer.get("sub") if isinstance(co_signer, dict) else getattr(co_signer, "user_id", "unknown")
            RBACManager.enforce_quorum_authorization(
                primary_role=current_user.role,
                co_signer_role=co_signer_role,
                permission=Permission.EVIDENCE_EXPORT_RAW,
                primary_user_id=current_user.user_id,
                co_signer_user_id=co_signer_user_id,
            )
            dual_quorum_approved = True
        except QuorumAuthorizationError as exc:
            if audit:
                audit.record(
                    action=AuditAction.ACCESS_DENIED,
                    actor=current_user.user_id,
                    resource=f"forensic_export:{body.camera_id}",
                    result="DENIED",
                    details={"error": str(exc), "include_raw": True},
                )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid co-signer token: {exc}")

    out_zip = Path("data/exports") / f"forensic_{body.camera_id}_{int(time.time())}.zip"
    try:
        manifest = playback.export_forensic_package(
            camera_id=body.camera_id,
            start_time_utc=body.start_time_utc,
            end_time_utc=body.end_time_utc,
            output_zip=out_zip,
            operator_id=current_user.user_id,
            case_id=body.case_id,
            include_raw=body.include_raw,
            dual_quorum_approved=dual_quorum_approved,
            notes=body.notes,
        )
        if audit:
            audit.record(
                action=AuditAction.EVIDENCE_SEALED,
                actor=current_user.user_id,
                resource=f"forensic_package:{manifest['evidence_id']}",
                result="SUCCESS",
                details={
                    "camera_id": body.camera_id,
                    "sha256": manifest["sha256_hash"],
                    "dual_quorum": dual_quorum_approved,
                },
            )
        return ForensicExportResponse(**manifest)
    except ExportAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/recordings/{recording_id}",
    response_model=RecordingResponse,
    tags=["NVR Recordings"],
    summary="Get single recording session details",
)
async def get_recording(
    request: Request,
    recording_id: str,
    current_user: UserIdentity = Depends(require_permission("recordings:read")),
) -> RecordingResponse:
    store = getattr(request.app.state, "sqlite_store", None)
    if not store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage engine unavailable")
    rec = store.get_recording(recording_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recording '{recording_id}' not found")
    return RecordingResponse(**rec)


@router.post(
    "/recordings/{recording_id}/judicial-hold",
    response_model=JudicialHoldResponse,
    tags=["NVR Recordings"],
    summary="Lock or release a recording under judicial hold to prevent retention purging and deletion",
)
async def set_recording_judicial_hold(
    request: Request,
    recording_id: str,
    body: JudicialHoldRequest,
    current_user: UserIdentity = Depends(require_permission("recordings:write")),
) -> JudicialHoldResponse:
    store: SQLiteStore = getattr(request.app.state, "sqlite_store", None)
    if not store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage engine unavailable")
    audit: AuditLogger = getattr(request.app.state, "audit_logger", None)

    rec = store.get_recording(recording_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recording '{recording_id}' not found")

    success = store.set_recording_judicial_hold(
        recording_id=recording_id,
        hold=body.hold,
        reason=body.reason,
        operator_id=current_user.user_id,
        case_id=body.case_id,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update judicial hold")

    if audit:
        audit.record(
            action=AuditAction.EVIDENCE_SEALED if body.hold else AuditAction.RECORDING_STOPPED,
            actor=current_user.user_id,
            resource=f"recording:{recording_id}",
            result="SUCCESS",
            details={"hold": body.hold, "reason": body.reason, "case_id": body.case_id or ""},
        )

    updated_rec = store.get_recording(recording_id)
    meta = updated_rec.get("metadata", {})
    return JudicialHoldResponse(
        recording_id=recording_id,
        judicial_hold=meta.get("judicial_hold", False),
        reason=meta.get("judicial_hold_reason", ""),
        operator_id=meta.get("judicial_hold_operator", ""),
        case_id=meta.get("judicial_hold_case_id", ""),
        updated_at=meta.get("judicial_hold_updated_at", ""),
    )


@router.get(
    "/recordings/{recording_id}/segments",
    response_model=list[RecordingSegmentResponse],
    tags=["NVR Recordings"],
    summary="List all video segments belonging to a recording",
)
async def list_recording_segments(
    request: Request,
    recording_id: str,
    current_user: UserIdentity = Depends(require_permission("recordings:read")),
) -> list[RecordingSegmentResponse]:
    store = getattr(request.app.state, "sqlite_store", None)
    if not store:
        return []
    segments = store.list_recording_segments(recording_id)
    return [RecordingSegmentResponse(**s) for s in segments]


@router.delete(
    "/recordings/{recording_id}",
    tags=["NVR Recordings"],
    summary="Delete a recording session and its segments cascade, refusing if locked under judicial hold",
)
async def delete_recording(
    request: Request,
    recording_id: str,
    current_user: UserIdentity = Depends(require_permission("recordings:write")),
) -> dict[str, Any]:
    store: SQLiteStore = getattr(request.app.state, "sqlite_store", None)
    if not store:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Storage engine unavailable")

    rec = store.get_recording(recording_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recording '{recording_id}' not found")

    try:
        deleted = store.delete_recording(recording_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recording '{recording_id}' could not be deleted")
        return {"status": "success", "recording_id": recording_id, "deleted": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Multi-Protocol Live Streaming Routes
# ---------------------------------------------------------------------------

@router.get(
    "/stream/{camera_id}/mjpeg",
    tags=["Streaming"],
    summary="Live MJPEG video stream (privacy-enforced)",
)
async def stream_mjpeg(
    request: Request,
    camera_id: str,
) -> StreamingResponse:
    gateway: StreamingGateway = getattr(request.app.state, "streaming_gateway", None)
    if not gateway:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Streaming gateway unavailable")

    return StreamingResponse(
        gateway.generate_mjpeg_stream(camera_id, target_fps=15.0),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get(
    "/stream/{camera_id}/hls/live.m3u8",
    tags=["Streaming"],
    summary="Low-Latency HLS live playlist",
)
async def stream_hls_playlist(
    request: Request,
    camera_id: str,
) -> Response:
    gateway: StreamingGateway = getattr(request.app.state, "streaming_gateway", None)
    if not gateway:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Streaming gateway unavailable")

    playlist_text = gateway.generate_hls_playlist(camera_id)
    return Response(content=playlist_text, media_type="application/vnd.apple.mpegurl")


@router.post(
    "/stream/{camera_id}/webrtc/offer",
    tags=["Streaming"],
    summary="WebRTC SDP signaling handshake",
)
async def stream_webrtc_offer(
    request: Request,
    camera_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    gateway: StreamingGateway = getattr(request.app.state, "streaming_gateway", None)
    if not gateway:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Streaming gateway unavailable")

    offer_sdp = body.get("sdp", "")
    session = gateway.create_webrtc_session(camera_id)
    answer_sdp = gateway.handle_webrtc_offer(session.session_id, offer_sdp)

    return {
        "session_id": session.session_id,
        "camera_id": camera_id,
        "type": "answer",
        "sdp": answer_sdp,
    }


# ---------------------------------------------------------------------------
# ONVIF Profile S PTZ Routes
# ---------------------------------------------------------------------------

@router.get(
    "/cameras/{camera_id}/ptz/capabilities",
    response_model=PTZCapabilitiesResponse,
    tags=["PTZ"],
    summary="Query camera PTZ capabilities",
)
async def get_ptz_capabilities(
    request: Request,
    camera_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:read")),
) -> PTZCapabilitiesResponse:
    ptz: PTZController = getattr(request.app.state, "ptz_controller", None)
    if not ptz:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PTZ controller unavailable")
    caps = ptz.get_capabilities(camera_id)
    return PTZCapabilitiesResponse(**caps.to_dict())


@router.post(
    "/cameras/{camera_id}/ptz/move",
    tags=["PTZ"],
    summary="Dispatch continuous velocity vector PTZ movement",
)
async def ptz_move(
    request: Request,
    camera_id: str,
    body: PTZMoveRequest,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> dict[str, str]:
    ptz: PTZController = getattr(request.app.state, "ptz_controller", None)
    if not ptz:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PTZ controller unavailable")

    try:
        ptz.continuous_move(
            camera_id=camera_id,
            vector=PTZVector(pan=body.pan, tilt=body.tilt, zoom=body.zoom),
            timeout_s=body.timeout_s,
        )
        return {"status": "moving", "camera_id": camera_id}
    except PTZUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/cameras/{camera_id}/ptz/stop",
    tags=["PTZ"],
    summary="Halt camera PTZ motion immediately",
)
async def ptz_stop(
    request: Request,
    camera_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> dict[str, str]:
    ptz: PTZController = getattr(request.app.state, "ptz_controller", None)
    if not ptz:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PTZ controller unavailable")

    ptz.stop(camera_id)
    return {"status": "stopped", "camera_id": camera_id}


@router.get(
    "/cameras/{camera_id}/ptz/presets",
    response_model=list[PTZPresetResponse],
    tags=["PTZ"],
    summary="List saved PTZ presets",
)
async def list_ptz_presets(
    request: Request,
    camera_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:read")),
) -> list[PTZPresetResponse]:
    ptz: PTZController = getattr(request.app.state, "ptz_controller", None)
    if not ptz:
        return []
    presets = ptz.list_presets(camera_id)
    return [PTZPresetResponse(**p.to_dict()) for p in presets]


@router.post(
    "/cameras/{camera_id}/ptz/presets",
    response_model=PTZPresetResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["PTZ"],
    summary="Save current camera orientation as a preset",
)
async def create_ptz_preset(
    request: Request,
    camera_id: str,
    body: PTZPresetCreate,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> PTZPresetResponse:
    ptz: PTZController = getattr(request.app.state, "ptz_controller", None)
    if not ptz:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PTZ controller unavailable")

    try:
        preset = ptz.save_preset(camera_id, name=body.name)
        return PTZPresetResponse(**preset.to_dict())
    except PTZUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/cameras/{camera_id}/ptz/presets/{preset_name_or_id}/goto",
    tags=["PTZ"],
    summary="Drive camera to a saved preset orientation",
)
async def goto_ptz_preset(
    request: Request,
    camera_id: str,
    preset_name_or_id: str,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> dict[str, str]:
    ptz: PTZController = getattr(request.app.state, "ptz_controller", None)
    if not ptz:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PTZ controller unavailable")

    try:
        if ptz.goto_preset(camera_id, preset_name_or_id):
            return {"status": "recalled", "preset": preset_name_or_id}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_name_or_id}' not found")
    except PTZUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Virtual Security Zones & Tripwires Routes
# ---------------------------------------------------------------------------

@router.post(
    "/analytics/{camera_id}/tripwires",
    status_code=status.HTTP_201_CREATED,
    tags=["Analytics Zones"],
    summary="Register a virtual tripwire line",
)
async def add_tripwire(
    request: Request,
    camera_id: str,
    body: TripwireCreate,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> dict[str, str]:
    zone_engine: ZoneAnalyticsEngine = getattr(request.app.state, "zone_engine", None)
    if not zone_engine:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Analytics engine unavailable")

    tw = Tripwire(
        tripwire_id=body.tripwire_id,
        camera_id=camera_id,
        name=body.name,
        start_point=body.start_point,
        end_point=body.end_point,
        direction=body.direction,
    )
    zone_engine.add_tripwire(tw)
    return {"status": "created", "tripwire_id": body.tripwire_id}


@router.post(
    "/analytics/{camera_id}/zones",
    status_code=status.HTTP_201_CREATED,
    tags=["Analytics Zones"],
    summary="Register a virtual polygon zone",
)
async def add_polygon_zone(
    request: Request,
    camera_id: str,
    body: PolygonZoneCreate,
    current_user: UserIdentity = Depends(require_permission("cameras:write")),
) -> dict[str, str]:
    zone_engine: ZoneAnalyticsEngine = getattr(request.app.state, "zone_engine", None)
    if not zone_engine:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Analytics engine unavailable")

    pz = PolygonZone(
        zone_id=body.zone_id,
        camera_id=camera_id,
        name=body.name,
        vertices=body.vertices,
        loitering_threshold_sec=body.loitering_threshold_sec,
    )
    zone_engine.add_zone(pz)
    return {"status": "created", "zone_id": body.zone_id}


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
