# CAMserv — Recording & AI Workload Isolation Architecture

**Document ID:** ARCH-P25-ISOLATION-2026-006  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25 — Hardware Adaptation & Appliance Engineering  
**Classification:** System Architecture & Fault-Isolation Standard  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Embedded Linux Engineer, Storage Reliability Engineer, Network Surveillance Architect, Security Engineer & Release Qualification Authority  

---

## 1. Executive Summary & Non-Negotiable Hierarchy

In professional physical security systems, **the video recording is the primary evidence.** An AI model that fails to detect a person is an analytical defect; a video recording engine that drops frames or crashes because an AI model crashed is a catastrophic operational failure.

**Core Architectural Rule:** The video ingestion and recording pipeline must be completely isolated from, and have absolute priority over, all optional AI analytics.

Under no circumstances may an AI failure, accelerator crash, model download error, or neural memory leak interrupt or pause the recording of live surveillance streams.

---

## 2. Decoupled Service & Resource Boundaries

CAMserv partitions its execution into eight independent, asynchronously decoupled subsystems:

```mermaid
graph TD
    subgraph Primary Subsystems (Critical Path)
        S1[1. Video Ingestion Pipeline] -->|Raw NALs| S2[2. Recording & Segment Finalization]
        S2 -->|Unmodified Stream| S3[3. Evidence Hashing & Handoff]
        S3 -->|Durable Commit| S4[4. Storage Management & Tier Pools]
    end

    subgraph Secondary Subsystems (Derivative Path)
        S1 -.->|Decoded Substream Copy| S5[5. AI Neural Inference Engine]
        S5 -->|Bounding Boxes / Classes| S6[6. Event Detection & Tracking]
        S6 -->|Alert Records| S8[8. Database & Metadata Ledger]
    end

    subgraph Presentation Subsystem
        S8 --> S7[7. Operator User Interface]
    end
```

### 2.1 Boundary Isolation Invariants

| Subsystem | Execution Priority | Failure Action | Impact on Core Video Recording |
| :--- | :---: | :--- | :---: |
| **1. Video Ingestion** | **CRITICAL (P0)** | Socket retry with exponential backoff & jitter. | Ingestion engine preserves incoming network packets. |
| **2. Recording & Finalization**| **CRITICAL (P0)** | Sequential segmented write (`.part` to `.h264/.h265`). | **ZERO IMPACT** — Commits 100% of received frames. |
| **3. Evidence Hashing** | **CRITICAL (P0)** | Streaming SHA-256 computation over raw bytes. | **ZERO IMPACT** — Hashing occurs in-flight during write. |
| **4. Storage Management** | **HIGH (P1)** | Verified 8-step transfer to warm archive pool. | **ZERO IMPACT** — Staging buffers absorb I/O wait. |
| **5. AI Neural Inference** | **OPTIONAL (P2)**| Crash caught by supervisor; shed to CPU or halted. | **ZERO IMPACT** — Recording continues 100% unaffected. |
| **6. Event Detection** | **OPTIONAL (P2)**| Event suppressed; failure logged in telemetry. | **ZERO IMPACT** — Recording continues 100% unaffected. |
| **7. User Interface** | **INTERACTIVE (P3)**| Asynchronous polling timeout; zero lock contention. | **ZERO IMPACT** — Recording runs in detached worker. |
| **8. Database & Metadata** | **HIGH (P1)** | SQLite WAL transactional replay; fail-closed. | **ZERO IMPACT** — Holds preserved; recordings immutable. |

---

## 3. Resilience Scenarios: Recording Continuity Guarantees

CAMserv guarantees continuous video recording across all of the following failure modes:

1. **System Without Discrete GPU:**
   - CAMserv initializes without error on CPU-only machines. Video recording proceeds at full native camera resolution and frame rate.
2. **AI Service Disabled or Model Missing:**
   - Operators may disable AI globally or per-camera. Recording continues natively with zero overhead.
3. **AI Accelerator Driver Crash / CUDA Out-of-Memory:**
   - If an NVIDIA driver resets or VRAM saturates, the AI worker is isolated by `WorkerCrashSupervisor`. The accelerator is marked `FAILED` and inference falls back to CPU. Video recording continues without dropping a single frame.
4. **AI Inference Backlog / Slow Processing:**
   - If AI inference takes 150ms per frame while the camera is delivering 30 FPS (33ms per frame), the `ingest_to_ai` queue applies `DROP_OLDEST`. The AI pipeline drops intermediate preview frames to maintain real-time tracking, while the `ingest_to_recording` queue records all 30 frames to disk.
5. **AI Derivatives Cannot Mutate Evidence:**
   - Neural detection boxes, privacy masks, and tracking IDs are stored as external metadata overlays. The original camera elementary stream is preserved byte-for-byte in its pristine, court-admissible form.
