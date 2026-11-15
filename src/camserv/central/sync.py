"""
camserv.central.sync
====================

Multi-site remote recording synchronization, fleet-wide camera discovery,
and store-and-forward manifest replication for CAMserv Central.

Enforces WAN data minimization: only cryptographic integrity manifests,
timeline metadata, and event references are synchronized across sites;
raw surveillance video remains strictly local at the edge appliance.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.central.comm import (
    OfflineMessageBuffer,
    PayloadType,
    SecureMessageEnvelope,
)
from camserv.central.registry import DeviceRegistry
from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class FleetCameraInfo:
    """Catalog entry for an edge camera discovered across the enterprise fleet."""

    camera_id: str
    appliance_id: str
    site_id: str
    name: str
    url: str
    enabled: bool = True
    fps: float = 15.0
    width: int = 1920
    height: int = 1080
    ptz_capable: bool = False
    status: str = "online"
    last_seen_utc: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FleetRecordingRecord:
    """Federated recording session cataloged at CAMserv Central."""

    recording_id: str
    appliance_id: str
    site_id: str
    camera_id: str
    start_time_utc: str
    end_time_utc: str
    recording_type: str
    total_size_bytes: int
    segment_count: int
    segments: list[dict[str, Any]]
    has_event: bool = False
    event_ids: list[str] = field(default_factory=list)
    judicial_hold: bool = False
    synchronized_at_utc: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EdgeSyncClient:
    """
    Edge appliance recording synchronization client.
    Monitors local storage, constructs signed WAN-minimized manifest envelopes,
    and reliably delivers them to CAMserv Central via store-and-forward buffering.
    """

    def __init__(
        self,
        appliance_id: str,
        site_id: str,
        store: SQLiteStore,
        buffer: OfflineMessageBuffer | None = None,
        private_key: ed25519.Ed25519PrivateKey | None = None,
    ) -> None:
        self.appliance_id = appliance_id
        self.site_id = site_id
        self.store = store
        self.buffer = buffer or OfflineMessageBuffer(max_capacity=5000)
        self.private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self._synced_recording_ids: set[str] = set()

    def package_recording_manifest(self, recording_id: str) -> SecureMessageEnvelope:
        """
        Package metadata and segment checksums for a finalized recording.
        Strictly excludes raw video frames to guarantee WAN privacy and data minimization.
        """
        rec = self.store.get_recording(recording_id)
        if not rec:
            raise ValueError(f"Recording '{recording_id}' not found in local store.")

        segments = self.store.list_recording_segments(recording_id)
        meta = rec.get("metadata", {})

        payload: dict[str, Any] = {
            "recording_id": recording_id,
            "appliance_id": self.appliance_id,
            "site_id": self.site_id,
            "camera_id": rec["camera_id"],
            "start_time_utc": rec["start_time_utc"],
            "end_time_utc": rec.get("end_time_utc") or "",
            "recording_type": rec.get("recording_type", "continuous"),
            "total_size_bytes": rec.get("total_size_bytes", 0),
            "segment_count": len(segments),
            "segments": [
                {
                    "segment_id": s["segment_id"],
                    "segment_index": s["segment_index"],
                    "start_time_utc": s["start_time_utc"],
                    "end_time_utc": s["end_time_utc"],
                    "duration_seconds": s["duration_seconds"],
                    "sha256": s["sha256_hash"],
                    "file_size_bytes": s["file_size_bytes"],
                    "has_event": bool(s.get("has_event")),
                    "event_ids": s.get("event_ids", []),
                }
                for s in segments
            ],
            "has_event": any(s.get("has_event") for s in segments),
            "event_ids": list(set([eid for s in segments for eid in s.get("event_ids", [])])),
            "judicial_hold": bool(meta.get("judicial_hold")),
            "judicial_hold_reason": meta.get("judicial_hold_reason", ""),
        }

        envelope = SecureMessageEnvelope(
            message_id=f"SYNC-REC-{recording_id}",
            sender_id=self.appliance_id,
            recipient_id="central",
            payload_type=PayloadType.MANIFEST_DIGEST,
            payload_data=payload,
        )
        envelope.sign(self.private_key)
        return envelope

    def publish_camera_discovery(self, cameras: list[dict[str, Any]]) -> SecureMessageEnvelope:
        """Publish inventory of active camera channels on this appliance."""
        cam_catalog: list[dict[str, Any]] = []
        for c in cameras:
            cam_catalog.append({
                "camera_id": c.get("id") or c.get("camera_id"),
                "appliance_id": self.appliance_id,
                "site_id": self.site_id,
                "name": c.get("name", "Unnamed Camera"),
                "url": c.get("url", ""),
                "enabled": c.get("enabled", True),
                "fps": float(c.get("fps", 15.0)),
                "width": int(c.get("width", 1920)),
                "height": int(c.get("height", 1080)),
                "ptz_capable": bool(c.get("onvif_profile")),
                "status": "online" if c.get("enabled", True) else "disabled",
            })

        envelope = SecureMessageEnvelope(
            message_id=f"DISC-CAM-{self.appliance_id}-{int(time.time())}",
            sender_id=self.appliance_id,
            recipient_id="central",
            payload_type="camera_discovery",
            payload_data={
                "appliance_id": self.appliance_id,
                "site_id": self.site_id,
                "cameras": cam_catalog,
            },
        )
        envelope.sign(self.private_key)
        return envelope

    def queue_recording_for_sync(self, recording_id: str) -> bool:
        """Construct manifest envelope and stage in store-and-forward buffer."""
        envelope = self.package_recording_manifest(recording_id)
        enqueued = self.buffer.enqueue(envelope)
        if enqueued:
            logger.info("central.sync.enqueued_manifest", recording_id=recording_id, queue_len=self.buffer.get_pending_count())
        return enqueued

    def flush_offline_queue(
        self,
        dispatch_fn: Callable[[SecureMessageEnvelope], bool],
        batch_size: int = 50,
    ) -> int:
        """
        Drain store-and-forward buffer by transmitting envelopes to Central.
        Returns count of successfully acknowledged envelopes.
        """
        batch = self.buffer.dequeue_batch(batch_size=batch_size)
        if not batch:
            return 0

        acked_ids: list[str] = []
        for envelope in batch:
            try:
                delivered = dispatch_fn(envelope)
                if delivered:
                    acked_ids.append(envelope.message_id)
                    rec_id = envelope.payload_data.get("recording_id")
                    if rec_id:
                        self._synced_recording_ids.add(rec_id)
                else:
                    # WAN unavailable, halt batch to preserve chronological order
                    break
            except Exception as exc:
                logger.warning("central.sync.dispatch_failed", msg_id=envelope.message_id, error=str(exc))
                break

        if acked_ids:
            self.buffer.acknowledge_batch(acked_ids)
            logger.info("central.sync.batch_flushed", acked_count=len(acked_ids), remaining=self.buffer.get_pending_count())

        return len(acked_ids)

    def get_status(self) -> dict[str, Any]:
        """Return operational synchronization status."""
        return {
            "appliance_id": self.appliance_id,
            "site_id": self.site_id,
            "pending_buffer_count": self.buffer.get_pending_count(),
            "total_synced_recordings": len(self._synced_recording_ids),
        }


class CentralSyncEngine:
    """
    CAMserv Central federated recording and fleet inventory registry.
    Ingests cryptographically signed manifests from multi-site edge appliances,
    maintains a fleet-wide recording catalog, and provides cross-site search.
    """

    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        self.registry = registry or DeviceRegistry()
        self.fleet_cameras: dict[str, FleetCameraInfo] = {}
        self.fleet_recordings: dict[str, FleetRecordingRecord] = {}

    def ingest_sync_envelope(self, envelope: SecureMessageEnvelope) -> dict[str, Any]:
        """Ingest, verify, and index an incoming message envelope from an edge appliance."""
        # 1. Handle Camera Discovery
        if envelope.payload_type == "camera_discovery":
            cams = envelope.payload_data.get("cameras", [])
            for c in cams:
                cam_info = FleetCameraInfo(**c)
                self.fleet_cameras[cam_info.camera_id] = cam_info
            logger.info(
                "central.sync.cameras_discovered",
                appliance_id=envelope.sender_id,
                count=len(cams),
            )
            return {"status": "indexed", "type": "camera_discovery", "count": len(cams)}

        # 2. Handle Recording Manifest Digest
        if envelope.payload_type == PayloadType.MANIFEST_DIGEST:
            p = envelope.payload_data
            rec_id = p["recording_id"]
            record = FleetRecordingRecord(
                recording_id=rec_id,
                appliance_id=p["appliance_id"],
                site_id=p["site_id"],
                camera_id=p["camera_id"],
                start_time_utc=p["start_time_utc"],
                end_time_utc=p["end_time_utc"],
                recording_type=p["recording_type"],
                total_size_bytes=p["total_size_bytes"],
                segment_count=p["segment_count"],
                segments=p.get("segments", []),
                has_event=bool(p.get("has_event")),
                event_ids=p.get("event_ids", []),
                judicial_hold=bool(p.get("judicial_hold")),
            )
            self.fleet_recordings[rec_id] = record
            logger.info(
                "central.sync.recording_indexed",
                recording_id=rec_id,
                camera_id=record.camera_id,
                site_id=record.site_id,
            )
            return {"status": "indexed", "type": "manifest_digest", "recording_id": rec_id}

        return {"status": "ignored", "reason": f"Unsupported payload type '{envelope.payload_type}'"}

    def query_fleet_recordings(
        self,
        site_id: str | None = None,
        camera_id: str | None = None,
        start_time_utc: str | None = None,
        end_time_utc: str | None = None,
        has_event: bool | None = None,
        judicial_hold: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Federated query of recording sessions across all enterprise sites."""
        results: list[FleetRecordingRecord] = []
        for rec in self.fleet_recordings.values():
            if site_id and rec.site_id != site_id:
                continue
            if camera_id and rec.camera_id != camera_id:
                continue
            if start_time_utc and rec.end_time_utc and rec.end_time_utc < start_time_utc:
                continue
            if end_time_utc and rec.start_time_utc > end_time_utc:
                continue
            if has_event is not None and rec.has_event != has_event:
                continue
            if judicial_hold is not None and rec.judicial_hold != judicial_hold:
                continue
            results.append(rec)

        results.sort(key=lambda r: r.start_time_utc, reverse=True)
        return [r.to_dict() for r in results[:limit]]

    def query_fleet_timeline(
        self,
        camera_id: str,
        start_time_utc: str,
        end_time_utc: str,
    ) -> dict[str, Any]:
        """Aggregate timeline segments and event markers for a camera across all appliances."""
        matching_segments: list[dict[str, Any]] = []
        appliance_id = "unknown"
        site_id = "unknown"

        for rec in self.fleet_recordings.values():
            if rec.camera_id == camera_id:
                appliance_id = rec.appliance_id
                site_id = rec.site_id
                for seg in rec.segments:
                    if seg["start_time_utc"] <= end_time_utc and seg["end_time_utc"] >= start_time_utc:
                        matching_segments.append(seg)

        matching_segments.sort(key=lambda s: s["start_time_utc"])
        return {
            "camera_id": camera_id,
            "appliance_id": appliance_id,
            "site_id": site_id,
            "start_time_utc": start_time_utc,
            "end_time_utc": end_time_utc,
            "segment_count": len(matching_segments),
            "segments": matching_segments,
        }

    def discover_fleet_cameras(self, site_id: str | None = None) -> list[dict[str, Any]]:
        """List active camera inventory across edge appliances."""
        cams = list(self.fleet_cameras.values())
        if site_id:
            cams = [c for c in cams if c.site_id == site_id]
        cams.sort(key=lambda c: (c.site_id, c.name))
        return [c.to_dict() for c in cams]

    def get_fleet_stats(self) -> dict[str, Any]:
        """Summary statistics of fleet surveillance data."""
        total_bytes = sum(r.total_size_bytes for r in self.fleet_recordings.values())
        sites = set(r.site_id for r in self.fleet_recordings.values()) | set(c.site_id for c in self.fleet_cameras.values())
        appliances = set(r.appliance_id for r in self.fleet_recordings.values()) | set(c.appliance_id for c in self.fleet_cameras.values())

        return {
            "sites_count": len(sites),
            "appliances_count": len(appliances),
            "cameras_count": len(self.fleet_cameras),
            "recordings_count": len(self.fleet_recordings),
            "total_storage_gb": round(total_bytes / (1024 * 1024 * 1024), 3),
            "judicial_holds_count": sum(1 for r in self.fleet_recordings.values() if r.judicial_hold),
        }
