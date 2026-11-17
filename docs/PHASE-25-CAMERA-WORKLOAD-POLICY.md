# CAMserv — Camera Workload & AI Sampling Policy Specification

**Document ID:** POL-P25-CAMERA-WORKLOAD-2026-010  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25 — Hardware Adaptation & Appliance Engineering  
**Classification:** Operational Policy & Resource Efficiency Standard  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Embedded Linux Engineer, Storage Reliability Engineer, Network Surveillance Architect, Security Engineer & Release Qualification Authority  

---

## 1. Executive Summary & Efficiency Architecture

A common failure in surveillance software is attempting to run high-resolution 4K video through convolutional neural networks at full camera frame rate (30 FPS) for every channel. Decoding and analyzing 16 streams of 4K30 video would require over $15,000 in specialized server hardware and hundreds of watts of power.

CAMserv achieves enterprise performance on modest, low-power hardware through a **Dual-Stream Workload Architecture**:
1. **Primary High-Resolution Stream (Mainstream):** Ingested and written directly to disk via native pass-through without decoding or transcoding. Preserves 100% of forensic video quality at near-zero CPU cost.
2. **Secondary Low-Resolution Stream (Substream):** Decoded at lower resolution ($640 \times 360$ or $720 \times 480$) and sampled at 2 to 10 FPS for neural object detection and tracking.
3. **Event-Triggered Escalation:** When a threat, tripwire breach, or perimeter violation is detected on the substream, the engine temporarily escalates analytics to evaluate full-resolution keyframe snapshots.

---

## 2. Dual-Stream Video Routing Architecture

```mermaid
graph TD
    CAM[IP Surveillance Camera] -->|Mainstream: 4K / 1080p30 H.265 (High Bitrate)| S_MAIN[RTSP Demuxer: Main Stream]
    CAM -->|Substream: 360p / D1 @ 10-15 FPS (Low Bitrate)| S_SUB[RTSP Demuxer: Sub Stream]

    subgraph Zero-CPU Recording Path
        S_MAIN -->|Zero-Copy NAL Packaging| REC[Sequential Segment Writer]
        REC -->|128MB Aggregation| DISK[(Encrypted Storage Pool)]
    end

    subgraph Resource-Efficient AI Path
        S_SUB -->|Low-Cost HW/CPU Decode| DEC[Lightweight Frame Decoder]
        DEC -->|Sampled at 2-10 FPS| AI[Neural Detection Engine]
        AI -->|Tripwire / Zone Breach| ESCALATE[Event-Triggered Escalation Trigger]
    end

    ESCALATE -.->|Extract Pristine Forensic Crop| S_MAIN
```

---

## 3. Workload Comparison: Monolithic vs. Dual-Stream Efficiency

| Performance Dimension | Monolithic Ingestion (Single Stream Decoded & Recorded) | CAMserv Dual-Stream Architecture (Main Recorded, Substream Analyzed) | Operational Gain |
| :--- | :---: | :---: | :---: |
| **Decode Pixel Rate (16 Cams)** | $16 \times 1920 \times 1080 \times 30 \approx \mathbf{995.3\text{ MPix/s}}$ | $16 \times 640 \times 360 \times 10 \approx \mathbf{36.8\text{ MPix/s}}$ | **96.3% Compute Reduction** |
| **Video Decoding Load** | Requires dedicated GPU / high-end CPU ($> 85\%$ CPU) | Lightweight; executes easily on low-power Intel QSV / CPU ($< 15\%$ CPU) | **Runs on Fanless Hardware** |
| **Neural Inference Flops** | $16 \times 30\text{ FPS} = 480\text{ passes/sec}$ | $16 \times 5\text{ FPS} = 80\text{ passes/sec}$ (Event-escalated) | **83.3% Inference Reduction** |
| **Recording Quality** | Often forced to downscale recording to save CPU | Pristine 4K / 1080p native camera quality preserved byte-for-byte | **100% Forensic Evidence** |

---

## 4. Configurable Camera Workload Policies

Every camera channel in CAMserv is governed by a granular configuration policy:

```json
{
  "camera_id": "cam_gatehouse_01",
  "recording_policy": {
    "enabled": true,
    "stream_type": "main",
    "target_fps": 30,
    "codec": "native_pass_through",
    "segment_duration_sec": 300
  },
  "analytics_policy": {
    "enabled": true,
    "stream_type": "substream",
    "nominal_fps": 5,
    "degraded_fps": 2,
    "event_burst_fps": 15,
    "burst_duration_sec": 10,
    "models": ["yolov8_person_vehicle"],
    "backend_preference": ["intel_qsv", "cpu_universal"]
  }
}
```

### 4.1 Unsupported Codec & Missing Substream Handling
- If a camera does not support secondary RTSP substreams, CAMserv downsamples the primary decoded frames in software using a bounded queue (`QueueOverflowPolicy.DROP_OLDEST`), ensuring the recording path is never degraded.
- If a camera stream uses an unsupported proprietary compression wrapper, CAMserv records the raw elementary stream directly to disk without modification and reports:
  `"Analytics Offline: Unsupported stream encapsulation; recording preserved in pass-through mode."`
