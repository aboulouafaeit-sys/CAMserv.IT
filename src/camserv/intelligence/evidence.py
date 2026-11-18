"""
camserv.intelligence.evidence
=============================

Evidence Capture, Provenance & Cryptographic Linkage Engine.

Enforces:
- Non-Destructive Association: Raw video streams and recorded segments are
  NEVER mutated, overwritten, or modified with AI bounding box overlays.
- Cryptographic Linkage: Every intelligence observation links to the raw video
  segment ID, frame ID, and SHA-256 hash of the exact source image bytes.
- Derived Artifact Isolation: Crops, detection metadata, and ANPR records
  are explicitly tagged `is_derived_artifact=True`.
- Epistemic Integrity: Evidence integrity proves that a frame was analyzed,
  NEVER that an AI prediction is an infallible ground truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from typing import Any

import cv2
import numpy as np

from camserv.intelligence.contracts import (
    BoundingBox,
    EngineHealthStatus,
    EvidenceLink,
    IntelligenceEvent,
)


class EvidenceProvenanceEngine:
    """
    Manages immutable forensic links between AI intelligence artifacts
    and original raw surveillance recordings.
    """

    def __init__(self, artifacts_base_dir: str = "data/evidence/intelligence") -> None:
        self.artifacts_dir = artifacts_base_dir
        self._lock = threading.RLock()
        self._evidence_records: dict[str, EvidenceLink] = {}
        self._health_status = EngineHealthStatus.ACTIVE
        os.makedirs(self.artifacts_dir, exist_ok=True)

    @property
    def health_status(self) -> EngineHealthStatus:
        with self._lock:
            return self._health_status

    @property
    def total_records(self) -> int:
        with self._lock:
            return len(self._evidence_records)

    def create_evidence_link(
        self,
        event: IntelligenceEvent,
        raw_frame: np.ndarray,
        crop_bbox: BoundingBox | None = None,
        model_id: str = "camserv_det_cpu_v1",
        model_hash: str = "sha256_mock_model",
    ) -> EvidenceLink:
        """
        Generate a verifiable provenance record and optionally persist a cropped
        forensic evidence snippet without mutating original recordings.
        """
        now = time.time()
        evidence_id = f"evl_{uuid.uuid4().hex[:12]}"

        # Compute SHA-256 hash of raw frame bytes
        frame_bytes = raw_frame.tobytes()
        frame_sha256 = hashlib.sha256(frame_bytes).hexdigest()

        crop_path = ""
        with self._lock:
            if crop_bbox is not None and raw_frame.size > 0:
                h, w = raw_frame.shape[:2]
                x1 = max(0, min(w - 1, int(crop_bbox.x1)))
                y1 = max(0, min(h - 1, int(crop_bbox.y1)))
                x2 = max(x1 + 1, min(w, int(crop_bbox.x2)))
                y2 = max(y1 + 1, min(h, int(crop_bbox.y2)))

                crop = raw_frame[y1:y2, x1:x2]
                if crop.size > 0:
                    crop_filename = f"{evidence_id}_{event.event_type.value.lower()}.png"
                    crop_path = os.path.join(self.artifacts_dir, crop_filename)
                    try:
                        cv2.imwrite(crop_path, crop)
                    except Exception:
                        crop_path = f"memory://{evidence_id}"

            link = EvidenceLink(
                evidence_id=evidence_id,
                event_id=event.event_id,
                camera_id=event.camera_id,
                timestamp_utc=now,
                segment_id=event.source_segment_id,
                frame_id=event.source_frame_id,
                frame_sha256=frame_sha256,
                derived_artifact_path=crop_path,
                model_id=model_id,
                model_hash=model_hash,
                is_derived_artifact=True,
            )
            self._evidence_records[evidence_id] = link
            return link

    def verify_evidence_integrity(
        self,
        evidence_id: str,
        current_frame: np.ndarray,
    ) -> bool:
        """
        Cryptographically verify that a given raw frame matches the evidence record.
        """
        with self._lock:
            record = self._evidence_records.get(evidence_id)
            if not record:
                return False

            current_hash = hashlib.sha256(current_frame.tobytes()).hexdigest()
            return current_hash.lower() == record.frame_sha256.lower()

    def get_evidence_link(self, evidence_id: str) -> EvidenceLink | None:
        """Retrieve an evidence provenance record by ID."""
        with self._lock:
            return self._evidence_records.get(evidence_id)
