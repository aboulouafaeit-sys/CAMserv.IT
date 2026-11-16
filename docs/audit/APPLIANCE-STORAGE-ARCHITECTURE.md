# CAMserv — Appliance Storage Architecture & FHS Directory Layout

**Document ID:** STR-ARCH-P13-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Distribution:** Debian 13 (Trixie)  
**Standard Compliance:** Linux Foundation Filesystem Hierarchy Standard (FHS 3.0)  
**Date:** November 16, 2026  
**Auditor:** Principal Linux Appliance Architect & Forensics Engineer  

---

## 1. Executive Summary & Design Principles

A production NVR appliance requires strict isolation between ephemeral application code, system configuration, continuous recording partitions, and tamper-evident forensic evidence vaults.

In CAMserv, storage is architectured around four non-negotiable principles:
1. **FHS 3.0 Conformance:** Strict alignment with Debian standard directory semantics (`/opt`, `/etc`, `/var/lib`, `/var/log`, `/var/cache`).
2. **Failure Isolation:** Exhaustion of the video recording disk partition must never cause database corruption, audit trail failure, or OS kernel panic.
3. **Forensic Immutability:** Evidence vault files (`/var/lib/camserv/vault`) are stored with strict 0700 permissions and protected by judicial holds against retention purges or package removals.
4. **Partition Separation Readiness:** Designed to support independent block devices mounted at `/var/lib/camserv/recordings` (e.g., dedicated NVMe/SATA surveillance storage arrays).

---

## 2. Appliance Directory Architecture Matrix

| Path | Ownership | Permissions | Storage Lifetime | Purpose & Content |
| :--- | :---: | :---: | :--- | :--- |
| **`/opt/camserv`** | `camserv:camserv` | `0755` | Ephemeral (Package) | Application source code, manifests, and isolated Python virtualenv (`/opt/camserv/venv`). Removable on package purge. |
| **`/etc/camserv`** | `camserv:camserv` | `0700` | Permanent (Config) | Production settings (`camserv.yaml`), TLS keys, camera credential vault master secret. Protected via dpkg conffiles. |
| **`/var/lib/camserv/db`** | `camserv:camserv` | `0750` | Permanent (State) | Operational SQLite databases (`camserv.db`, `camserv.db-wal`, `camserv.db-shm`) and schema migration journals. |
| **`/var/lib/camserv/recordings`** | `camserv:camserv` | `0750` | Dynamic (Retention) | Continuous and scheduled MP4 video segments organized by camera ID and date (`{cam_id}/{YYYY-MM-DD}/rec_{id}_seg{idx}.mp4`). |
| **`/var/lib/camserv/vault`** | `camserv:camserv` | `0700` | Inviolate (Legal) | Cryptographically signed, Ed25519 tamper-evident ZIP evidence archives. Protected by statutory judicial hold locks. |
| **`/var/lib/camserv/exports`** | `camserv:camserv` | `0750` | Temporary (Exports) | User-requested forensic exports and signed judicial bundles prepared for operator download. |
| **`/var/lib/camserv/models`** | `camserv:camserv` | `0755` | Permanent (AI) | Pre-trained ONNX, OpenVINO IR, and TensorRT neural network model weights (`yolov8n.onnx`). |
| **`/var/log/camserv`** | `camserv:camserv` | `0750` | Permanent (Audit) | Operational daemon logs and append-only cryptographic hash-chained audit trails (`audit.jsonl`). |
| **`/var/cache/camserv`** | `camserv:camserv` | `0750` | Volatile (Cache) | Temporary video transcode scratch buffers and WebRTC keyframe caching. |
| **`/dev/shm`** | `root:root` | `1777` | RAM (In-Flight) | POSIX shared memory ring buffers (`/dev/shm/camserv-shm-*`) transferring 4K/1080p raw frames between processes. |

---

## 3. Recommended Storage Partitioning Topology

For physical appliances (Appliance OS Tier 2/Tier 3), the recommended disk layout enforces physical isolation:

| Mount Point | Filesystem | Recommended Size | Mount Options | Purpose |
| :--- | :---: | :---: | :--- | :--- |
| **`/`** | ext4 / OverlayFS | 32 GB | `ro` (Appliance Mode) | Immutable base OS image |
| **`/etc/camserv`** | ext4 | 2 GB | `rw,nodev,nosuid` | Appliance configuration |
| **`/var/lib/camserv/db`** | ext4 | 16 GB | `rw,nodev,nosuid,noatime` | High-IOPS NVMe SQLite WAL store |
| **`/var/lib/camserv/vault`** | ext4 / ZFS | 64 GB | `rw,nodev,nosuid,noexec` | Tamper-evident forensic incident vault |
| **`/var/lib/camserv/recordings`** | XFS / ext4 | 1–16 TB | `rw,nodev,nosuid,noatime` | High-throughput video block storage array |
| **`/var/log/camserv`** | ext4 | 16 GB | `rw,nodev,nosuid,noexec` | Append-only audit trail logging |

---

## 4. Quota Enforcement & Judicial Hold Safeguards

Storage space exhaustion is handled deterministically by `NVRRecordingEngine.enforce_storage_quota`:
1. When filesystem utilization exceeds `quota_max_usage_percent` (default: 90.0%), the engine identifies oldest unheld continuous recording segments.
2. **Judicial Hold Check:** Every candidate recording segment is verified against `store.get_recording(rec_id)`. If `judicial_hold == True` or `is_incident == True`, the segment is **strictly skipped** and preserved.
3. Once disk usage drops below threshold, purging stops immediately.
4. If all remaining footage is under judicial hold, the system asserts `STORAGE_FULL_HELD_ONLY` alarm and preserves evidence rather than corrupting court evidence.

---

## 5. Backward Compatibility Symlinks

To ensure seamless execution of legacy workflows or configurations targeting `/data`, `postinst` automatically deploys compatibility symlinks:
- `/data/db -> /var/lib/camserv/db`
- `/data/recordings -> /var/lib/camserv/recordings`
- `/data/vault -> /var/lib/camserv/vault`

This guarantees complete compatibility across older Phase scripts and standard Debian installations.
