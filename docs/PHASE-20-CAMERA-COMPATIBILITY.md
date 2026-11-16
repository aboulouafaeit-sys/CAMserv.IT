# CAMserv — Phase 20 Camera Protocol & Ingestion Compatibility

**Document ID:** PHASE-20-CAM-2026-011  
**Target Release:** `0.10.0`  
**Classification:** Hardware Verification & Ingestion Protocols  
**Date:** November 16, 2026  

---

## 1. Compliance Taxonomy & Evidence Classification

CAMserv classifies camera compatibility across distinct evidentiary tiers:

| Tier | Classification | Verification Criteria |
| :---: | :--- | :--- |
| **Tier 1** | `PHYSICAL_DEVICE_TESTED` | Real physical hardware camera connected over LAN/USB; optical frames captured. |
| **Tier 2** | `PHYSICAL_DEVICE_PARTIALLY_TESTED` | Real physical camera tested for RTSP video, but advanced PTZ or ONVIF events not evaluated. |
| **Tier 3** | `SYNTHETIC_PROTOCOL_TESTED` | Stream tested via automated FFmpeg/GStreamer RTSP servers in CI environment. |
| **Tier 4** | `MOCKED_TEST` | Camera stream acquisition mocked with synthetic numpy arrays. |
| **Tier 5** | `NOT_TESTED` | Camera model untested. |

---

## 2. Compatibility Matrix by Vendor

| Vendor / Device | Tested Series | Transport & Codec | Evidence Classification | Status & Observations |
| :--- | :--- | :--- | :---: | :--- |
| **Host Optical Webcam** | Integrated / USB UVC | DirectShow / MSMF (RGB 640x480 @ 30 FPS) | **PHYSICAL_DEVICE_TESTED** | 100% native acquisition verified on host Windows 11 machine. |
| **Hikvision** | DS-2CD2xx Series | RTSP / ONVIF Profile S (H.264 / H.265) | **SYNTHETIC_PROTOCOL_TESTED** | WS-Discovery, Digest Auth, Sub-stream pull verified in software testbed. |
| **Dahua** | IPC-HFW / HDW Series | RTSP / ONVIF Profile S (H.264 / H.265) | **SYNTHETIC_PROTOCOL_TESTED** | Video pull, dynamic framerate negotiation verified. |
| **Axis Communications** | M-Series, P-Series | RTSPS (TLS) / ONVIF Profile S/T (H.264) | **SYNTHETIC_PROTOCOL_TESTED** | TLS handshake, Digest authentication verified. |
| **Hanwha Techwin** | Wisenet X & Q Series | RTSP / ONVIF Profile S (H.264 / H.265) | **SYNTHETIC_PROTOCOL_TESTED** | H.265 stream negotiation with fallback to H.264 verified. |
| **Ubiquiti UniFi** | UniFi Protect G4/G5 | RTSPS (Standalone Mode) | **SYNTHETIC_PROTOCOL_TESTED** | High-bitrate H.264 RTSP pull verified. |

---

## 3. Operational Fencing Invariants

1. **StorageLease Binding:** Every active camera channel is bound to a single cluster node with an epoch token. If a node is partitioned, its local write lease expires and it is halted.
2. **Graceful Codec Fallback:** If camera RTSP negotiation fails for H.265, CAMserv automatically attempts H.264 negotiation.
3. **PTZ Honesty:** For cameras without motorized PTZ actuators, UI controls are disabled with an explicit indicator ("PTZ Unsupported"). No simulated motion vectors are fabricated.
