"""
camserv.storage.isep.retention_engine
=====================================

Policy-Based Retention Engine for CAMserv ISEP.
Executes the mandatory 6-step safe cleanup lifecycle:
  1. Identify eligible candidate segments.
  2. Verify that no active preservation hold or evidence lock applies.
  3. Check policy thresholds (per-camera, per-pool, event vs continuous).
  4. Record planned deletion plan before modifying filesystem.
  5. Execute authorized deletion.
  6. Record results into structured audit log.

Never silently purges data due to disk pressure.
Strictly respects legal, incident, and administrative preservation holds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.isep.evidence_preservation import EvidencePreservationManager
from camserv.storage.isep.models import (
    RecordingSegmentMetadata,
    SegmentState,
    StorageTierType,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class CameraRetentionRule:
    """Specific retention duration rule for a camera or camera group."""

    continuous_retention_hours: float = 48.0   # 2 days baseline
    event_retention_days: float = 30.0         # 30 days for motion/event segments
    incident_retention_days: float = 365.0     # 1 year for tagged incidents
    min_retention_hours: float = 24.0          # Minimum guarantee; never purge below this


@dataclass(slots=True)
class CleanupAuditEntry:
    """Audit log entry capturing an authorized segment purge operation."""

    segment_id: str
    camera_id: str
    file_path: str
    size_bytes: int
    freed_at_utc: str
    reason: str
    rule_applied: str


class RetentionPolicyEngine:
    """
    Coordinates policy evaluation, hold checks, and non-destructive retention enforcement.
    """

    def __init__(
        self,
        evidence_manager: EvidencePreservationManager,
        default_rule: CameraRetentionRule | None = None,
    ) -> None:
        self.evidence_manager = evidence_manager
        self.default_rule = default_rule or CameraRetentionRule()
        self.camera_rules: dict[str, CameraRetentionRule] = {}
        self.audit_trail: list[CleanupAuditEntry] = []

    def set_camera_retention_rule(self, camera_id: str, rule: CameraRetentionRule) -> None:
        """Assign custom retention policies to a specific camera."""
        self.camera_rules[camera_id] = rule

    def evaluate_retention(
        self,
        segments: list[RecordingSegmentMetadata],
        now: float | None = None,
    ) -> tuple[list[RecordingSegmentMetadata], list[str]]:
        """
        Evaluate candidate segments for retention compliance without deleting them.
        Returns: (eligible_for_deletion, preserved_by_hold)
        """
        current_time = now if now is not None else time.time()
        eligible: list[RecordingSegmentMetadata] = []
        protected: list[str] = []

        for seg in segments:
            # Step 2: Verify that no preservation hold or vault lock applies
            if seg.is_protected_evidence or seg.tier == StorageTierType.EVIDENCE_VAULT:
                protected.append(seg.segment_id)
                continue

            if self.evidence_manager.is_target_protected(seg.segment_id) or self.evidence_manager.is_target_protected(seg.recording_id):
                protected.append(seg.segment_id)
                continue

            # Step 3: Check policy thresholds
            rule = self.camera_rules.get(seg.camera_id, self.default_rule)
            try:
                # Parse start time
                start_dt = datetime.fromisoformat(seg.start_time_utc)
                age_seconds = current_time - start_dt.timestamp()
            except Exception:
                age_seconds = 0.0

            # Absolute safeguard: Never purge before min_retention_hours
            if age_seconds < (rule.min_retention_hours * 3600.0):
                continue

            # Event / incident segments retain longer
            if seg.has_event or seg.event_ids:
                max_age_sec = rule.incident_retention_days * 86400.0
            elif seg.has_motion:
                max_age_sec = rule.event_retention_days * 86400.0
            else:
                max_age_sec = rule.continuous_retention_hours * 3600.0

            if age_seconds >= max_age_sec:
                eligible.append(seg)

        return eligible, protected

    def execute_safe_cleanup(
        self,
        segments: list[RecordingSegmentMetadata],
        operator_authorization: str = "SYSTEM_RETENTION_POLICY",
        now: float | None = None,
    ) -> dict[str, Any]:
        """
        Executes the mandatory 6-step safe cleanup lifecycle.
        Only deletes files once eligibility and non-preservation are confirmed.
        """
        eligible, protected = self.evaluate_retention(segments, now=now)

        # Step 4: Record planned deletion plan
        planned_count = len(eligible)
        planned_bytes = sum(s.file_size_bytes for s in eligible)
        logger.info(
            "isep.retention_cleanup_planned",
            planned_count=planned_count,
            planned_mb=round(planned_bytes / (1024 * 1024), 2),
            protected_count=len(protected),
            authorized_by=operator_authorization,
        )

        purged_ids: list[str] = []
        freed_bytes = 0

        # Step 5: Execute authorized deletion
        for seg in eligible:
            try:
                p = Path(seg.file_path).resolve()
                if p.is_file():
                    p.unlink()

                freed_bytes += seg.file_size_bytes
                purged_ids.append(seg.segment_id)
                seg.state = SegmentState.PURGED

                # Step 6: Record result in audit trail
                audit_entry = CleanupAuditEntry(
                    segment_id=seg.segment_id,
                    camera_id=seg.camera_id,
                    file_path=seg.file_path,
                    size_bytes=seg.file_size_bytes,
                    freed_at_utc=datetime.now(timezone.utc).isoformat(),
                    reason=f"Exceeded retention age ({seg.duration_seconds}s segment)",
                    rule_applied=operator_authorization,
                )
                self.audit_trail.append(audit_entry)

            except Exception as exc:
                logger.error("isep.purge_failed_on_segment", segment_id=seg.segment_id, error=str(exc))

        logger.info(
            "isep.retention_cleanup_completed",
            purged_count=len(purged_ids),
            freed_mb=round(freed_bytes / (1024 * 1024), 2),
        )

        return {
            "purged_count": len(purged_ids),
            "freed_bytes": freed_bytes,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
            "protected_count": len(protected),
            "purged_segment_ids": purged_ids,
        }
