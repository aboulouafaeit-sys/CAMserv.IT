# CAMserv — Phase 25.1-B Durable Continuity Ledger Report

**Document ID:** QUAL-P25.1B-CONTINUITY-2026-017  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25.1-B — Stage B  
**Date:** November 17, 2026  
**Module:** `camserv.storage.continuity_store`  
**Class:** `DurableContinuityStore`  
**Auditor Roles:** Principal Storage Architect, SQLite Forensics Specialist & Data Durability Engineer  

---

## 1. Executive Summary & Problem Definition

In Phase 25.1 and 25.1-A, recording continuity tracking was performed in-memory inside `RecordingContinuityLedger`, with periodic `to_dict()` and `from_dict()` serialization.

### The Problem: Memory Volatility & Unclean Crashes
If the host server experienced an abrupt power outage, kernel panic, or forced process kill (`SIGKILL` / `TerminateProcess`), all in-memory segment continuity state was lost. Upon reboot, the application could not differentiate whether an incomplete recording was continuous or interrupted, risking fraudulent or unverified continuous recording claims in court or regulatory audits.

### The Solution: SQLite WAL-Backed Durable Ledger
Phase 25.1-B introduces `DurableContinuityStore` in [src/camserv/storage/continuity_store.py](file:///c:/Users/MPront/Documents/CAMserv/src/camserv/storage/continuity_store.py), a dedicated transactional persistence engine using SQLite WAL mode (`PRAGMA journal_mode = WAL;`) and synchronous normal mode (`PRAGMA synchronous = NORMAL;`).

---

## 2. Durable Schema & Transaction Architecture

### 2.1 Database Tables & Versioning
The database implements two primary tables with relational foreign keys and indices:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuity_segments (
    segment_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    start_timestamp_utc TEXT NOT NULL,
    end_timestamp_utc TEXT,
    expected_frames INTEGER DEFAULT 0,
    observed_frames INTEGER DEFAULT 0,
    current_state TEXT NOT NULL,
    confirmed_missing_frames_total INTEGER DEFAULT 0,
    estimated_missing_frames_total INTEGER DEFAULT 0,
    unknown_frame_loss_events INTEGER DEFAULT 0,
    reconnect_events INTEGER DEFAULT 0,
    storage_write_errors INTEGER DEFAULT 0,
    last_frame_seq INTEGER,
    last_frame_pts REAL,
    is_finalized INTEGER DEFAULT 0,
    integrity_verified INTEGER DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuity_events (
    event_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    segment_id TEXT,
    gap_start_utc TEXT NOT NULL,
    gap_end_utc TEXT NOT NULL,
    gap_duration_sec REAL NOT NULL,
    lost_frames_estimated INTEGER DEFAULT 0,
    confirmed_missing_frames INTEGER,
    estimated_missing_frames INTEGER,
    unknown_frame_loss INTEGER DEFAULT 0,
    estimation_method TEXT NOT NULL,
    confidence TEXT NOT NULL,
    reason TEXT NOT NULL,
    recovery_status TEXT NOT NULL,
    last_confirmed_pts REAL,
    first_subsequent_pts REAL,
    last_confirmed_seq INTEGER,
    subsequent_seq INTEGER,
    source_metadata_json TEXT,
    detected_at_utc TEXT NOT NULL,
    FOREIGN KEY (segment_id) REFERENCES continuity_segments(segment_id) ON DELETE SET NULL
);
```

### 2.2 Idempotent Upsert & Event Deduplication
- **Segments:** Saved using `INSERT ... ON CONFLICT(segment_id) DO UPDATE SET ...`, allowing real-time progress updates without row duplication.
- **Discontinuity Events:** Saved using `INSERT OR IGNORE INTO continuity_events ...` using deterministic or UUID event IDs, preventing gap event inflation during retries or reconnections.

---

## 3. Unclean Shutdown Recovery (`recover_unclean_shutdown()`)

### 3.1 The Integrity Guarantee
When the system reboots after an unexpected crash:
1. `DurableContinuityStore.load_unfinalized_segments()` queries all segments where `is_finalized = 0`.
2. For each unfinalized segment:
   - State is transitioned to `RECORDING_INTERRUPTED`.
   - `is_finalized` is set to `True`.
   - An explicit crash discontinuity event is appended:
     - `reason`: `"PROCESS_ABRUPT_TERMINATION_OR_POWER_CUT"`
     - `estimation_method`: `"unclean_shutdown_recovery"`
     - `unknown_frame_loss`: `True`
   - The recovered segment and event are committed to SQLite.
3. **Forensic Integrity Rule:** Under no circumstances can a segment interrupted by a crash be claimed as `CONTINUOUS`.

---

## 4. Separation of Recording Path & Degraded Persistence

### 4.1 Non-Blocking Architecture
A key architectural requirement is that persistence operations MUST NOT block high-speed video ingestion threads (30–60 fps).

- Ingest threads record frames into memory buffers in microseconds.
- Persistence commits occur asynchronously or at bounded checkpoint intervals.
- If SQLite is locked, disk write errors occur, or storage becomes full:
  - `is_persistence_degraded` is set to `True`.
  - In-memory continuity tracking continues uninterrupted.
  - No exceptions are propagated to the frame ingest loop.
  - Once storage recovers, subsequent transactions clear the degraded flag.

---

## 5. Verification Test Matrix

All 7 Stage B tests were executed natively on Windows 11 Enterprise (`ACTUALLY_EXECUTED_ON_WINDOWS`):

| Test Case | Invariant Verified | Status |
| :--- | :--- | :---: |
| `test_durable_continuity_store_initialization_wal` | SQLite WAL mode, synchronous NORMAL, schema version 1 | **PASS** |
| `test_durable_continuity_segment_persistence_and_upsert` | Idempotent upsert of segment progress and state transitions | **PASS** |
| `test_durable_continuity_event_persistence_and_deduplication` | Deduplication of discontinuity events by event ID | **PASS** |
| `test_durable_continuity_unclean_shutdown_recovery` | Unfinalized active segment converted to `RECORDING_INTERRUPTED` with crash record | **PASS** |
| `test_ledger_integration_with_durable_store` | Seamless rehydration of records across application restart | **PASS** |
| `test_persistence_degradation_without_blocking_recording` | DB failure sets `is_persistence_degraded=True` without blocking frame ingest | **PASS** |
| `test_concurrent_multi_camera_events_in_continuity_store` | 8 concurrent camera threads writing 40 segments and 40 events simultaneously | **PASS** |

---

## 6. Conclusion & Acceptance Decision

The Durable Continuity Ledger meets all Stage B requirements. It eliminates the risk of silent continuity corruption across power loss or process kill events, ensuring 100% forensic defensibility.
