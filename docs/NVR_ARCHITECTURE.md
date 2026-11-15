# CAMserv NVR Architecture & Engineering Specification

**Document ID:** ARCH-NVR-2026-001  
**Classification:** Technical Architecture Specification  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Subsystem Overview

The **CAMserv NVR** subsystem transforms the platform into an enterprise Network Video Recorder capable of 24/7 continuous recording, scheduled recording, intelligent event-triggered capture with pre-roll buffering, synchronized multi-camera timeline playback, fast search, and court-admissible clipped export.

```
                          ┌──────────────────────────────┐
                          │   Camera Stream Ingestion    │
                          │      (RTSP / ONVIF S)        │
                          └──────────────┬───────────────┘
                                         │
                                         ▼
                          ┌──────────────────────────────┐
                          │  Fail-Closed Privacy Gate    │
                          └──────────────┬───────────────┘
                                         │
             ┌───────────────────────────┴───────────────────────────┐
             ▼                                                       ▼
┌─────────────────────────────┐                         ┌─────────────────────────────┐
│ 15s RAM Circular Buffer     │                         │   Recording Engine Service  │
│      (Lookback Memory)      │                         │  (Schedule / Event / Manual)│
└────────────┬────────────────┘                         └────────────┬────────────────┘
             │                                                       │
             │ Stitch on Event Trigger                               │ Write Chunks (60s)
             └───────────────────────────┬───────────────────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │   Segmented Video Storage    │
                          │   (Operational NVMe Pool)    │
                          └──────────────┬───────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
┌─────────────────────────────────────┐     ┌─────────────────────────────────────┐
│    Relational Indexing (SQLite WAL) │     │    Playback & Timeline Service      │
│  - Segment Start / End UTC          │     │  - Multi-camera synchronized seek   │
│  - Keyframe Offsets & Byte Lengths  │     │  - Event & motion marker overlays   │
│  - Motion & Event Flags             │     │  - Clipped range export (MP4/ZIP)   │
└─────────────────────────────────────┘     └─────────────────────────────────────┘
```

---

## 2. Core Functional Requirements

### 2.1 Camera Management & Credential Vault (`camserv.nvr.credentials`, `camserv.nvr.groups`)
- **Secure Credential Vault:** Camera passwords and RTSP authentication secrets are encrypted at rest using AES-256-GCM under key-versioned secrets.
- **Logical Organization:** Cameras are organized into logical groups, physical sites, floors, and security zones.
- **Configuration Backup & Restore:** Camera settings can be exported to encrypted backup packages and restored atomically.

### 2.2 Recording Engine & Modes (`camserv.nvr.recording_engine`)
The recording engine supports three operational modes per camera:
1. **Continuous 24/7 Recording:** Streams are continuously written to disk in configurable chunk lengths (default: 60 seconds). Each segment is finalized with a clean container moov atom and registered in the relational index.
2. **Event-Triggered Recording (with Lookback):** Upon receiving a security event or motion alert:
   - The engine retrieves the preceding 15 seconds from the RAM circular buffer (Pre-Roll / Lookback).
   - Stitches the pre-roll footage to the active event recording.
   - Continues recording for the event duration plus a configurable post-roll period (default: 30 seconds).
3. **Scheduled Recording (`camserv.nvr.recording_scheduler`):** Cameras adhere to granular weekly schedules (e.g., continuous recording during business hours, event-only recording during off-hours, recording disabled during maintenance).

### 2.3 Recording Playback & Timeline (`camserv.nvr.playback`)
- **Multi-Camera Timeline:** Delivers sub-second timeline queries across multiple cameras, highlighting available recording spans, motion intensity, and confirmed security events.
- **Synchronized Playback:** Allows operators to navigate multiple camera feeds simultaneously using synchronized UTC timestamps.
- **Speed & Stepping Controls:** Supports variable playback speeds ($0.25\times, 0.5\times, 1\times, 2\times, 4\times, 8\times, 16\times$) and forward/backward frame-by-frame stepping.
- **Clipped Export:** Operators can select arbitrary start and end times to export a standalone MP4 file or an Ed25519-signed forensic evidence ZIP package.

### 2.4 ONVIF Profile S & PTZ Control (`camserv.nvr.ptz`)
- **Continuous & Absolute Movement:** Pan, tilt, and zoom commands with configurable velocity vectors.
- **Preset Management:** Saving and recalling named PTZ presets (e.g., "Main Gate", "Loading Dock").
- **PTZ Status & Capability Query:** Probing whether a camera supports continuous move, relative move, or absolute positioning.

---

## 3. Data Schema & Relational Storage

The NVR recording metadata is durably persisted in SQLite with Write-Ahead Logging (WAL) enabled:

```sql
CREATE TABLE IF NOT EXISTS recordings (
    recording_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    start_time_utc TEXT NOT NULL,
    end_time_utc TEXT,
    recording_type TEXT NOT NULL, -- 'continuous', 'event', 'manual'
    status TEXT NOT NULL,        -- 'recording', 'finalized', 'corrupted'
    storage_tier TEXT NOT NULL,  -- 'operational', 'vault', 'archive'
    total_size_bytes INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recording_segments (
    segment_id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    start_time_utc TEXT NOT NULL,
    end_time_utc TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    has_motion INTEGER DEFAULT 0,
    has_event INTEGER DEFAULT 0,
    event_ids TEXT DEFAULT '[]',
    FOREIGN KEY(recording_id) REFERENCES recordings(recording_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recording_schedules (
    schedule_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    day_of_week INTEGER NOT NULL, -- 0=Monday, 6=Sunday
    start_time TEXT NOT NULL,     -- HH:MM
    end_time TEXT NOT NULL,       -- HH:MM
    mode TEXT NOT NULL,           -- 'continuous', 'event', 'disabled'
    is_active INTEGER DEFAULT 1
);
```

---

## 4. Resilience and Crash Recovery

- **Atomic Segment Finalization:** Segments are written to temporary files (`.part`) and renamed atomically to `.mp4` upon completion.
- **Startup Scanner:** On service startup, the NVR engine scans the storage directory for abandoned `.part` files, repairs incomplete MP4 headers using moov atom recovery, indexes them, and logs an audit recovery event.
- **Disk Quota Auto-Purge:** If storage utilization exceeds the configured threshold (default: 90%), the oldest non-judicial-hold continuous recordings are purged first, preserving event clips and forensic vault material.
