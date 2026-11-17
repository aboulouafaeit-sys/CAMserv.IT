"""
camserv.storage.isep.recovery_manager
=====================================

Storage Recovery Manager for CAMserv ISEP.
Handles post-crash recovery, sudden power failure reconciliation,
unverified staging transfer resolution, partial-write quarantine,
and recording continuity gap detection.
Never overwrites valid copies; produces comprehensive forensic recovery reports.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.isep.integrity_verifier import StorageIntegrityVerifier
from camserv.storage.isep.models import RecordingSegmentMetadata, SegmentState
from camserv.storage.isep.segment_manager import RecordingSegmentManager
from camserv.storage.isep.tier_manager import StorageTierManager

logger = structlog.get_logger(__name__)


class StorageRecoveryManager:
    """
    Orchestrates crash recovery and storage consistency repair.
    """

    def __init__(
        self,
        segment_manager: RecordingSegmentManager,
        tier_manager: StorageTierManager,
        verifier: StorageIntegrityVerifier | None = None,
    ) -> None:
        self.segment_manager = segment_manager
        self.tier_manager = tier_manager
        self.verifier = verifier or StorageIntegrityVerifier()

    def execute_post_crash_recovery(
        self,
        known_segments: list[RecordingSegmentMetadata],
    ) -> dict[str, Any]:
        """
        Execute automated crash recovery sequence upon service startup:
          1. Recover orphaned '.part' files left unfinalized.
          2. Reclaim aborted '.staging_transfer' files.
          3. Verify completeness across known segments.
          4. Categorize records: Complete, Incomplete, Corrupted, Unverified Transfer, Protected Evidence.
        """
        report_timestamp = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        # Step 1: Recover orphaned .part files
        recovered_parts = self.segment_manager.recover_orphaned_part_files()

        # Step 2: Clean up partial staging transfer attempts
        cleaned_staging = self.tier_manager.recover_interrupted_transfers()

        # Step 3 & 4: Audit known segments
        complete_count = 0
        incomplete_count = 0
        corrupted_count = 0
        protected_evidence_count = 0
        unverified_transfers = 0

        corrupted_records: list[str] = []

        all_segments = known_segments + recovered_parts

        for seg in all_segments:
            if seg.is_protected_evidence:
                protected_evidence_count += 1

            if seg.state == SegmentState.TRANSFERRING:
                unverified_transfers += 1
                incomplete_count += 1
                continue

            if seg.state == SegmentState.RECOVERED_PARTIAL or seg.is_partial:
                incomplete_count += 1
                continue

            check = self.verifier.verify_segment_integrity(seg)
            if check["is_valid"]:
                complete_count += 1
            else:
                corrupted_count += 1
                corrupted_records.append(seg.segment_id)
                seg.state = SegmentState.CORRUPTED
                logger.warning(
                    "isep.recovery.corrupted_segment_detected",
                    segment_id=seg.segment_id,
                    error=check.get("error"),
                )

        elapsed_ms = (time.time() - t0) * 1000.0

        recovery_status = "CLEAN"
        if corrupted_count > 0:
            recovery_status = "DEGRADED_CORRUPTED_FOUND"
        elif incomplete_count > 0:
            recovery_status = "RECOVERED_PARTIALS_FOUND"

        recovery_report = {
            "recovery_timestamp_utc": report_timestamp,
            "elapsed_ms": round(elapsed_ms, 2),
            "recovered_orphaned_parts": len(recovered_parts),
            "recovered_partial_recordings": len(recovered_parts),
            "cleaned_interrupted_staging_transfers": cleaned_staging,
            "total_segments_evaluated": len(all_segments),
            "complete_recordings": complete_count,
            "incomplete_recordings": incomplete_count,
            "corrupted_recordings": corrupted_count,
            "protected_evidence_count": protected_evidence_count,
            "unverified_transfers": unverified_transfers,
            "corrupted_segment_ids": corrupted_records,
            "recovery_status": recovery_status,
        }

        logger.info(
            "isep.crash_recovery_completed",
            recovered_parts=len(recovered_parts),
            corrupted=corrupted_count,
            clean=corrupted_count == 0,
        )

        return recovery_report
