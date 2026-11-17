"""
camserv.storage.isep.integrity_verifier
=======================================

Storage Integrity Verifier & Cryptographic Deduplication Evaluator.
Validates on-disk video segments against recorded SHA-256 hashes,
detects silent bitrot, truncated writes, and unauthorized modifications.
Enforces Rule 10: Deduplication is permitted ONLY when cryptographic byte equivalence
is proven, and never merges different camera feeds or alters timestamps.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import structlog

from camserv.storage.isep.models import RecordingSegmentMetadata, SegmentState

logger = structlog.get_logger(__name__)


class StorageIntegrityVerifier:
    """
    Executes deep and background integrity checks on stored video segments.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def compute_file_sha256(file_path: Path | str) -> str:
        """Compute SHA-256 digest of an on-disk file."""
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found for hash verification: {p}")

        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def verify_segment_integrity(self, segment: RecordingSegmentMetadata) -> dict[str, Any]:
        """
        Verify that on-disk segment exists, is readable, matches size, and matches SHA-256.
        """
        p = Path(segment.file_path).resolve()
        if not p.exists():
            return {
                "segment_id": segment.segment_id,
                "is_valid": False,
                "error": "FILE_MISSING",
                "details": f"File does not exist: {p}",
            }

        try:
            actual_size = p.stat().st_size
            if actual_size != segment.file_size_bytes:
                return {
                    "segment_id": segment.segment_id,
                    "is_valid": False,
                    "error": "SIZE_MISMATCH",
                    "expected_size": segment.file_size_bytes,
                    "actual_size": actual_size,
                    "details": "Segment file size does not match metadata.",
                }

            actual_hash = self.compute_file_sha256(p)
            if actual_hash != segment.sha256_hash:
                return {
                    "segment_id": segment.segment_id,
                    "is_valid": False,
                    "error": "SHA256_MISMATCH",
                    "expected_hash": segment.sha256_hash,
                    "actual_hash": actual_hash,
                    "details": "Cryptographic hash mismatch. Potential tampering or silent bitrot.",
                }

            return {
                "segment_id": segment.segment_id,
                "is_valid": True,
                "size_bytes": actual_size,
                "sha256_hash": actual_hash,
                "details": "Integrity verified successfully.",
            }
        except Exception as exc:
            return {
                "segment_id": segment.segment_id,
                "is_valid": False,
                "error": "READ_ERROR",
                "details": str(exc),
            }

    def evaluate_cryptographic_deduplication(
        self,
        candidate_segment: RecordingSegmentMetadata,
        existing_segments: list[RecordingSegmentMetadata],
    ) -> dict[str, Any]:
        """
        Safely evaluate whether a segment can share underlying content storage.
        Strict Rules:
          1. Exact SHA-256 equality is mandatory.
          2. Camera identity and timestamp metadata are NEVER altered or merged.
          3. If byte hashes match exactly, permits hardlinking or reference sharing.
        """
        exact_matches = [
            s for s in existing_segments
            if s.segment_id != candidate_segment.segment_id and s.sha256_hash == candidate_segment.sha256_hash
        ]

        if not exact_matches:
            return {
                "can_deduplicate": False,
                "reason": "Unique content-addressed payload",
                "matched_segment_id": None,
                "potential_savings_bytes": 0,
            }

        match = exact_matches[0]
        return {
            "can_deduplicate": True,
            "reason": "Cryptographically proven byte equivalence (SHA-256 match)",
            "matched_segment_id": match.segment_id,
            "matched_camera_id": match.camera_id,
            "potential_savings_bytes": candidate_segment.file_size_bytes,
            "is_cross_camera": match.camera_id != candidate_segment.camera_id,
        }
