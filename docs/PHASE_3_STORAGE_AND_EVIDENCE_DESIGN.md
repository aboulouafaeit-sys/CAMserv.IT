# CAMserv — Phase 3 Storage & Forensic Evidence Architecture

**Document ID:** ARCH-STORAGE-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Stage 6 Deliverable  
**Date:** November 15, 2026  
**Status:** PRODUCTION STORAGE & EVIDENCE BLUEPRINT  
**Author / Authority:** Database & Storage Engineer, Digital Forensics Specialist & Chief Software Architect  

---

## 1. Executive Summary & Design Scope

Video surveillance systems in enterprise and municipal environments generate continuous high-bitrate data streams that place severe demands on storage throughput, write endurance, disk health, and retention governance. Under **GDPR Article 5(1)(e) (Storage Limitation)** and European Data Protection Board (EDPB) surveillance guidelines, continuous video must be systematically purged according to strict retention schedules unless explicitly flagged as evidence for judicial proceedings.

**Stage 6** engineers a robust, multi-tiered storage architecture, an automated retention and judicial hold purge engine, a zero-dependency transactional database migration framework, and a court-admissible evidence export packager.

### Core Storage Invariants:
1. **Tiered Storage Segregation:** Continuous raw streams, RAM pre-roll buffers, and encrypted forensic vaults occupy distinct hardware tiers to optimize throughput and endurance.
2. **Definite Configurable Retention:** CAMserv rejects indefinite retention by default. Standard non-incident footage purges after a configurable threshold (default: 48 hours).
3. **Judicial Hold Immutability:** When a security incident is flagged under judicial hold (`judicial_hold = True`), it is locked against automated purging until formally released by an authorized legal officer.
4. **Dual-Control Quorum for Pristine Raw Evidence Extraction:** Exporting unmasked pristine video from the vault requires co-signing by both a Forensic Investigator and a Tenant/Super Administrator. Unilateral raw export is blocked.
5. **Zero-Dependency Transactional Database Migrations:** Schema evolution across appliance over-the-air updates is managed via forward and backward transactional migrations with cryptographic checksum verification.

---

## 2. Multi-Tiered Storage Pool Architecture

```
+─────────────────────────────────────────────────────────────────────────────────+
|                         CAMSERV TIERED STORAGE MODEL                            |
+─────────────────────────────────────────────────────────────────────────────────+
| TIER 0: Volatile Pre-Roll Buffer | 15s to 30s continuous uncompressed RAM ring. |
|                                  | Instantaneous incident trigger capture.      |
+──────────────────────────────────+──────────────────────────────────────────────+
| TIER 1: Operational Storage Pool | Fast local NVMe SSD (PCIe 4.0 x4).           |
| (Continuous Rolling Retention)   | Rolling 48-hour continuous encrypted chunks. |
|                                  | Automated circular FIFO purge.               |
+──────────────────────────────────+──────────────────────────────────────────────+
| TIER 2: Forensic Evidence Vault  | Dedicated high-capacity surveillance array.  |
| (Immutable Incident Archives)    | AES-256-GCM chunk encryption, Ed25519 sign.  |
|                                  | Linked to SQLite manifest indices.           |
|                                  | Retained 365 days / Judicial Hold locking.   |
+──────────────────────────────────+──────────────────────────────────────────────+
| TIER 3: Cold / Secondary Archive | Off-site S3 / NFS court-ready export archive.|
+─────────────────────────────────────────────────────────────────────────────────+
```

---

## 3. Automated Retention Purging & Judicial Hold Engine

Implemented in `src/camserv/storage/tiered_storage.py`:

```python
def evaluate_retention_and_purge(now: float) -> dict[str, Any]:
    # 1. Standard chunks older than continuous_retention_hours (48h) are unlinked
    # 2. Incident chunks older than incident_retention_days (365d) are unlinked
    # 3. Chunks with judicial_hold = True are ALWAYS PRESERVED regardless of age
```

### Storage Limitation Guarantees:
* Continuous non-incident surveillance files are unlinked from disk and database catalogs once their timestamp crosses the 48-hour cutoff.
* Incidents flagged with `is_incident = True` are retained for legal discovery.
* Applying `set_judicial_hold(chunk_id, hold=True, reason="Court Subpoena #...")` prevents automated purging even if the incident crosses the 365-day threshold.

---

## 4. Court-Admissible Evidence Export Package Specification

When an investigator extracts evidence for legal proceedings or law enforcement handover:
1. **Packaging Format:** Single standard zip package containing:
   - `manifest.json`: Metadata, timestamp, operator ID, camera ID, SHA-256 digest, dual quorum approval token.
   - `evidence/`: Derivative video files with non-biometric privacy masking and forensic enhancement metadata.
   - `raw_pristine/`: Unmasked original video chunk (present **only** if `dual_quorum_approved = True`).
   - `signature.ed25519`: Digital signature of `manifest.json` generated by the appliance's private key.
2. **Dual-Control Quorum Verification:** If `include_raw = True` is requested without verified dual-control co-signing, `export_courtroom_evidence_package` raises `ExportAuthorizationError`.

---

## 5. Zero-Dependency Database Schema Migration Framework

Implemented in `src/camserv/storage/migrations.py`:

```
[Migration 1: Base Schema] ──► [Migration 2: Manifest Tables] ──► [Migration 3: Multi-Tenancy]
```

### Key Engineering Features:
* **Transactional Execution:** Every migration runs within `BEGIN TRANSACTION; ... COMMIT;`. If an exception occurs, the transaction is immediately rolled back (`ROLLBACK`), preventing partially applied broken schemas.
* **Cryptographic Checksums:** Computes SHA-256 of the `up_sql` definition and stores it in `schema_migrations`. If a developer or attacker alters a previously applied migration file, the manager raises `MigrationError`.
* **Bidirectional Migrations:** Supports both forward migration (`migrate()`) and atomic backward rollback (`rollback(target_version)`).

---

## 6. Stage 6 Acceptance Decision

$$\mathbf{STAGE\_6\_ACCEPTANCE\_VERDICT: \quad ACCEPTED}$$

All deliverables for Stage 6 (Storage & Forensic Evidence Infrastructure) have been implemented, verified with 4 unit tests in `tests/test_tiered_storage.py`, and documented.
