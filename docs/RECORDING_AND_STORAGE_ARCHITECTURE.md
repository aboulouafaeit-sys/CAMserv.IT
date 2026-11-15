# CAMserv Recording and Storage Architecture

**Document ID:** ARCH-STORAGE-2026-001  
**Classification:** Technical Architecture Specification  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Storage Architecture Overview

CAMserv implements a tiered, privacy-aware storage hierarchy that balances high-speed I/O requirements, automated retention policies under GDPR, cryptographic evidence preservation, and disaster recovery.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Tier 0: RAM Ring Buffer                         │
│   Circular memory pool (15 seconds pre-roll per camera)               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
               ┌────────────────────┴────────────────────┐
               │ Continuous Write                        │ Event Trigger
               ▼                                         ▼
┌──────────────────────────────┐          ┌──────────────────────────────┐
│  Tier 1: Operational Storage │          │   Tier 2: Forensic Vault     │
│  - NVMe / Fast SSD pool      │          │  - AES-256-GCM Encrypted     │
│  - 60s Segmented MP4 chunks  │          │  - Merkle-linked SHA-256     │
│  - 48h Retention Purging     │          │  - WORM Judicial Hold Lock   │
│  - Auto-prune on 90% quota   │          │  - Dual-Control Access Gate  │
└──────────────┬───────────────┘          └──────────────┬───────────────┘
               │                                         │
               └────────────────────┬────────────────────┘
                                    │ Cold Archive Migration
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Tier 3: Cold Archive                            │
│   Network Attached Storage (NFS/SMB) or S3-compatible Object Storage    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Storage Tiers Specification

### 2.1 Tier 0: RAM Ring Buffer (Lookback / Pre-Roll)
- **Medium:** Volatile system memory (RAM).
- **Capacity:** Fixed circular buffer holding 15 seconds of uncompressed/partially compressed frames per camera at capture FPS.
- **Purpose:** Captures the crucial moments preceding an alarm or incident before an algorithmic threshold is breached.
- **Behavior:** Overwrites oldest frames automatically. When an event fires, frames are dumped and stitched to the recording.

### 2.2 Tier 1: Operational NVMe Pool (Continuous Recording)
- **Medium:** High-speed NVMe or SSD local filesystem.
- **Capacity:** Sized for 48 to 168 hours of continuous video per camera stream.
- **Segmentation:** Chunks are written in 60-second intervals in fragmented MP4 (fMP4) or standard MP4 format.
- **GDPR Compliance:** Standard surveillance recordings are automatically deleted after 48 hours unless tagged with an active incident or judicial hold.
- **Quota Safeguard:** If disk capacity reaches 90%, the oldest untagged continuous chunks are purged first to maintain continuous system uptime.

### 2.3 Tier 2: Encrypted Forensic Evidence Vault (Incidents)
- **Medium:** Local isolated filesystem or encrypted disk partition.
- **Security:** Each chunk and metadata file is encrypted with AES-256-GCM under key-versioned master keys managed by `KeyManager`.
- **Tamper Evidence:** Evidence records are chained using continuous SHA-256 hashes (`record_hash = SHA256(prev_hash : event_id : camera_id : timestamp : payload_hash)`).
- **WORM Protection:** Files are marked as Write-Once-Read-Many with judicial hold locks that prevent automated retention scripts or operator deletion.

### 2.4 Tier 3: Cold Archive (Long-Term Preservation)
- **Medium:** Secondary NAS (NFS/SMB share) or offsite S3-compatible cloud storage.
- **Migration:** Chunks older than 30 days tagged with long-term retention requirements are transferred with verifiable cryptographic manifests and removed from fast operational tiers.

---

## 3. Relational Indexing & Consistency

All recording files and segments are indexed in a transactional SQLite database with WAL mode:
- Queries for recordings by camera, time range, motion, or event tags execute in sub-millisecond time.
- Atomic transactions ensure that segment indices are never saved without corresponding files on disk.
- Periodic consistency checks verify that every database record points to an existing file with a valid SHA-256 checksum.
