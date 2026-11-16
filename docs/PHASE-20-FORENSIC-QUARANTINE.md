# CAMserv — Phase 20 Forensic Evidence Quarantine & Integrity

**Document ID:** PHASE-20-QUARANTINE-2026-006  
**Target Release:** `0.10.0`  
**Classification:** Digital Forensics Integrity & Evidence Custody  
**Date:** November 16, 2026  

---

## 1. Principles of Forensic Quarantine

In CAMserv, **quarantine never means deletion, truncation, or silent alteration**. Evidence recorded during a network partition, expired lease, or uncoordinated crash recovery represents potentially critical physical security footage.

Quarantine guarantees:
1. **Zero Evidence Loss:** The video media is preserved on disk in its entirety.
2. **Exclusion from Authoritative Evidence:** Quarantined segments are excluded from regular playback timelines, operator views, and automated exports to prevent contaminated evidence from entering court proceedings.
3. **Immutability:** The file is renamed to `.quarantined.mp4` via an atomic filesystem rename. The underlying byte stream is completely untouched.
4. **Byte-for-Byte Cryptographic Hash Equality:** The SHA-256 digest before quarantine and after quarantine are verified to be 100% byte-for-byte identical.

---

## 2. Quarantined Segment Audit Metadata

Every quarantined object generates an immutable audit record:

```json
{
  "evidence_id": "rec_cam-01_1794861931_s0004",
  "original_sha256": "4A1F89C0...",
  "post_quarantine_sha256": "4A1F89C0...",
  "hash_match": true,
  "camera_id": "cam-01",
  "recording_id": "rec_cam-01_1794861931",
  "segment_index": 4,
  "quarantined_path": "data/recordings/cam-01/2026-11-16/rec_..._s0004.quarantined.mp4",
  "file_size": 2048576,
  "assignment_epoch": 2,
  "reason": "storage_lease_expired_at_finalization",
  "quarantined_at": 1794863381.12
}
```

---

## 3. Privileged Operator Review & Restoration Lifecycle

When an investigation determines that a quarantined segment is legitimate (e.g., temporary network jitter delayed lease renewal but footage is uncorrupted and non-conflicting):

1. **Audit Inspection:** Operator queries quarantined recordings via `get_quarantined_segments()`.
2. **Cryptographic Validation:** `restore_quarantined_segment()` re-computes the file's SHA-256 hash and verifies it matches the recorded `original_sha256`.
3. **Controlled Re-admission:** The file is atomically renamed back to `.mp4` and registered in `SQLiteStore` under an authorized audit log entry naming the authorizing officer, timestamp, and justification.
4. **Tampered File Rejection:** If the quarantined file was tampered with on disk, restoration fails and raises an alert.

**Verification Status:** Tested and verified in `tests/test_pre_lts_phase20_qualification.py::test_forensic_quarantine_preserves_byte_for_byte_sha256` and `test_privileged_quarantine_restoration_lifecycle`.
