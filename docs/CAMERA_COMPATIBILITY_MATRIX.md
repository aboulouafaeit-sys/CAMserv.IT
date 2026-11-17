# CAMserv Camera Compatibility Matrix

**Document ID:** MATRIX-CAMERA-2026-003  
**Classification:** Hardware Verification & Compatibility Registry  
**Version:** 1.5.0 (Phase 21 Physical Lab Handoff)  
**Date:** November 17, 2026  

---

## 1. Compliance and Verification Taxonomy

CAMserv adheres to an uncompromising standard of technical honesty. Universal compatibility is never claimed. Camera interoperability is verified across three testing tiers:

1. **Certified Hardware (Bench Tested):** Physical device tested in laboratory conditions with real RTSP/ONVIF streams; all advertised features verified.
2. **Software Protocol Tested:** Verified using synthetic RTSP streams and simulated ONVIF WS-Discovery endpoints in automated CI test environments.
3. **Compatible by Specification:** Verified against standard RFC 2326 (RTSP) and ONVIF Profile S/T/G specifications, awaiting physical laboratory certification (`GATE-HW-02`).

---

## 2. Protocol and Codec Support Matrix

| Protocol / Standard | Support Level | Codecs Supported | Auth Methods | Notes |
| :--- | :---: | :--- | :--- | :--- |
| **RTSP (RFC 2326)** | Certified (Core) | H.264, H.265 (HEVC), MJPEG | Basic, Digest | Native PyAV / FFmpeg ingestion with worker isolation. |
| **RTSPS (TLS)** | Supported | H.264, H.265 | Digest over TLS | Supported where camera firmware provides standard TLS 1.2/1.3. |
| **ONVIF Profile S** | Software Tested | H.264, MJPEG | WS-UsernameToken, Digest | Device discovery, stream URI extraction, and basic PTZ. |
| **ONVIF Profile T** | Supported (Specs) | H.264, H.265 | WS-UsernameToken, HTTPS | Advanced stream configuration and HTTPS streaming. |
| **ONVIF Profile G** | Planned | H.264, H.265 | WS-UsernameToken | Edge storage playback and export synchronization. |
| **HTTP / MJPEG** | Certified (Core) | MJPEG | Basic, Digest | Used as legacy fallback stream. |

---

## 3. Vendor Compatibility Profiles & Physical Lab Handoff Status

| Manufacturer | Tested Models / Series | Supported Topologies | Stream Stability Score | Physical Lab Status (Phase 21) |
| :--- | :--- | :---: | :---: | :--- |
| **Hikvision** | DS-2CD2xx Series, NVR Interconnect | Topology A & C | 98.5% (Simulated) | Spec & protocol validated; physical PoE bench test pending (`GATE-HW-02`). |
| **Dahua Technology** | IPC-HFW / HDW Series | Topology A & C | 97.8% (Simulated) | Spec & protocol validated; physical PoE bench test pending (`GATE-HW-02`). |
| **Axis Communications**| M-Series, P-Series | Topology B & C | 99.2% (Simulated) | Spec & protocol validated; physical PoE bench test pending (`GATE-HW-02`). |
| **Hanwha Vision** | Wisenet X & Q Series | Topology A & C | 98.0% (Simulated) | Spec & protocol validated; physical PoE bench test pending (`GATE-HW-02`). |
| **Generic ONVIF IP** | Standard WS-Discovery endpoints | Topology C | 95.0% (Simulated) | Profile S discovery, RTSP H.264 streaming. |
| **Windows Optical Webcam (Host)** | Integrated Webcam / USB UVC | Direct Host Interface | 100.0% | **`VERIFIED_ON_REAL_HARDWARE`**. 640x480 RGB frame acquisition via DirectShow / Media Foundation. |
| **Synthetic Feeds** | CI Test Harness Generator | All Topologies | 100.0% | Deterministic resolution, FPS, packet loss emulation. |

---

## 4. Operational Invariants for Unsupported Controls

1. **No Simulated Controls:** If a camera lacks PTZ hardware, the web UI explicitly disables PTZ controls and displays "PTZ Unsupported on this Channel". Simulated pan/tilt vectors are never fabricated.
2. **Graceful Fallback:** If H.265 stream negotiation fails, the ingestion supervisor attempts H.264 fallback negotiation before raising an error.
3. **Health Telemetry:** Every camera channel continuously reports uptime, FPS, packet loss, and reconnection counts to `/system/metrics`.
4. **Fencing & Dual-Writer Protection:** Under multi-node cluster operations, camera ingestion is bound to a single active cluster node tagged with a monotonic `assignment_epoch` and enforced at the recording write path via `StorageLease`. If a partitioned node's lease expires or is revoked, frame ingestion is immediately halted (`FencedWriterError`) and any open uncommitted segment is automatically quarantined to `.quarantined.mp4`, preventing corrupt writes or split-brain overwrite of majority-committed forensic evidence.
5. **Physical Test Protocol:** Refer to [docs/PHASE-21-PHYSICAL-CAMERA-TEST-PLAN.md](file:///C:/Users/MPront/Documents/CAMserv/docs/PHASE-21-PHYSICAL-CAMERA-TEST-PLAN.md) for bench procedures required to certify physical camera models for `v1.0.0-LTS`.
