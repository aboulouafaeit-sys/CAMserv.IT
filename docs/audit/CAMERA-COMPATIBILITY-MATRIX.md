# CAMserv — Camera Compatibility & Interoperability Matrix

**Document ID:** AUDIT-CAM-MATRIX-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Classification:** Camera Compatibility Specification & Test Evidence  
**Date:** November 16, 2026  
**Auditor:** Independent IP Camera & Video Streaming Specialist  

---

## 1. Master Compatibility Matrix

This matrix documents the verified capabilities of CAMserv across physical hardware, emulated protocol targets, and enterprise camera models.

| Manufacturer | Exact Model | Firmware | Protocol | Codec | Resolution | FPS | RTSP | ONVIF | PTZ | Recording | Playback | Privacy | Reconnect | Test Date | Evidence Ref | Validation Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| **Integrated / OEM** | Integrated Camera (Index 0) | UVC 1.5 | Direct / V4L2 / MSMF | RAW RGB | 640x480 | 30 | N/A (Direct) | N/A (Direct) | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-REAL-CAM-01` | **`VERIFIED_ON_REAL_CAMERA`** |
| **Synthetic Engine** | CAMserv In-Memory Simulator | Builtin | Synthetic Ring Buffer | RAW RGB | 1920x1080 | 30 | PASS (Sim) | PASS (Sim) | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SYNTH-E2E` | **`VERIFIED_IN_SOFTWARE`** |
| **Hikvision** | DS-2CD2143G2-I (Fixed Dome) | V5.7.1 | RTSP / ONVIF Profile S/T | H.264 / H.265 | 2688x1520 | 25 | PASS | PASS | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-HIK-01` | **`SIMULATED`** |
| **Hikvision** | DS-2DE4425IW-DE (Speed Dome) | V5.7.3 | RTSP / ONVIF Profile S/T | H.264 / H.265 | 2560x1440 | 30 | PASS | PASS | PASS (Full PTZ) | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-HIK-02` | **`SIMULATED`** |
| **Dahua** | IPC-HFW5442T-ASE (Bullet) | V2.820 | RTSP / ONVIF Profile S/T | H.264 / H.265 | 2688x1520 | 25 | PASS | PASS | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-DAH-01` | **`SIMULATED`** |
| **Dahua** | SD49225XA-HNR (PTZ) | V2.812 | RTSP / ONVIF Profile S/T | H.264 / H.265 | 1920x1080 | 30 | PASS | PASS | PASS (Full PTZ) | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-DAH-02` | **`SIMULATED`** |
| **Axis** | P3245-V (Fixed Dome) | 10.12.215 | RTSP / ONVIF Profile S/T/G | H.264 / H.265 | 1920x1080 | 30 | PASS | PASS | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-AXIS-01` | **`SIMULATED`** |
| **Axis** | M5525-E (PTZ Dome) | 10.11.102 | RTSP / ONVIF Profile S/T | H.264 | 1920x1080 | 30 | PASS | PASS | PASS (Full PTZ) | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-AXIS-02` | **`SIMULATED`** |
| **Ubiquiti** | UniFi Protect G4 Pro | v4.64.150 | Standalone RTSP Re-Stream | H.264 | 3840x2160 | 24 | PASS | NOT_AVAILABLE | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-SIM-UBNT-01` | **`SIMULATED`** |
| **Generic ONVIF** | Compliant IP Camera Profile S | Any | ONVIF Profile S / RTSP | H.264 | 1920x1080 | 15-30 | PASS | PASS | NOT_SUPPORTED | PASS | PASS | PASS (Fail-Closed) | PASS | 2026-11-16 | `EVID-ONVIF-GEN` | **`SIMULATED`** |
| **Physical IP Cameras** | Hikvision/Dahua/Axis (Physical Units) | Various | Physical PoE Switch Link | H.264 / H.265 | Any | Any | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 2026-11-16 | N/A (No Physical PoE Lab) | **`NOT_TESTED`** |

---

## 2. Protocol Capability Validation Breakdown

### 2.1 RTSP Transport & Streaming Mechanics
* **RTSP Authentication:** Tested Basic and Digest authentication URI schemes. Remediated `SEC-P12-01` to ensure embedded credentials (`rtsp://user:pass@host`) are redacted before logging or storing in frame metadata.
* **TCP Interleaved Transport:** Validated TCP channel interleaving ($RTP=0, RTCP=1$), eliminating UDP packet drop across corporate firewalls.
* **Connection Timeout & Disconnection:** Simulated abrupt camera network severance; verified that `CameraStream` enters `CameraStatus.RECONNECTING` and initiates exponential backoff ($1.0\text{s} \to 2.0\text{s} \to 4.0\text{s} \dots \text{max } 30.0\text{s}$).
* **Camera Reboot Recovery:** Tested reconnection after prolonged disconnection (simulating 60s camera reboot); stream resumed automatically and finalized pending `.part` recording segments.

### 2.2 ONVIF Standard Conformance
* **Device Discovery (WS-Discovery):** Multicast UDP probing (`239.255.255.250:3702`) verified with SOAP `ProbeMatch` XML extraction.
* **Profile S (Basic Streaming):** Verified Media service profile enumeration, RTSP stream URI retrieval, and H.264 parameter negotiation.
* **Profile T (Advanced Streaming):** Validated H.265 codec signaling and event subscription schema.
* **Profile G (Edge Storage):** Tested manifest exchange for edge-recorded clip discovery.
* **Fixed Camera Protection:** Correctly distinguishes fixed optical cameras (`is_ptz_capable=False`) as `NOT_SUPPORTED` without raising runtime errors.

### 2.3 PTZ Mechanics & Command Dispatch
* **Continuous Velocity Vectors:** Pan, Tilt, and Zoom velocity commands clamped to $[-1.0, 1.0]$.
* **Motor Deceleration / Stop:** Verified immediate `stop()` command execution.
* **Preset Recall:** Tested saving and recalling pan/tilt/zoom coordinates via SQLite persistence.
* **Unsupported Protection:** Attempting PTZ commands on fixed cameras raises `PTZUnsupportedError` cleanly.

---

## 3. Physical Camera Hardware Acceptance Gate (v1.0.0-LTS)

To promote CAMserv from Release Candidate (`0.9.0-rc1`) to Long-Term Support (`v1.0.0-LTS`), the following physical camera laboratory trials must be conducted on an isolated 802.3at PoE switch network:
1. **Multi-Vendor Interoperability Lab:** Physical connection of at least one physical Hikvision (G2 series), one Dahua (WizMind series), and one Axis (ARTPEC-7/8 series) camera.
2. **Thermal & Day/Night Transition Test:** 24-hour continuous stream verification through physical IR-cut filter transitions.
3. **Motion Vector & Event Trigger Validation:** Verification of physical ONVIF motion alarm XML delivery into the CAMserv event pipeline.
