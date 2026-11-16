# Phase 15: Camera Capture Backend Architecture & Interoperability

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Scope:** Optical Camera Enumeration & Cross-Platform Ingestion Backends  
**Backends Evaluated:** Microsoft Media Foundation (MF), DirectShow (DSHOW), Video4Linux2 (V4L2)  

---

## 1. Unified Camera Ingestion Architecture

Camera acquisition in CAMserv is divided into two categories:
1. **Network IP Cameras (RTSP/ONVIF):** 100% OS-agnostic, using standard asynchronous TCP/UDP socket connections. Identical on Linux and Windows.
2. **Local Optical Cameras (USB/Integrated):** Mediated by platform adapters to interface with operating system driver stacks.

```text
                                [CameraManager]
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
         [Network Streams (RTSP)]              [Local Optical Cameras]
                    │                                     │
           (Platform-Agnostic)                 [PlatformCameraBackend]
                    │                                     │
                    │                    ┌────────────────┴────────────────┐
                    │                    ▼                                 ▼
                    │         [LinuxV4L2CameraBackend]     [WindowsMFCameraBackend]
                    │              (/dev/video*)                  (CAP_MSMF)
                    ▼                    │                                 │
         [OpenCV / FFmpeg Demux] ◄───────┴─────────────────────────────────┘
                    │
                    ▼
         [Decoupled Ring Buffer & Fail-Closed Privacy Pipeline]
```

---

## 2. Comparison of Windows Camera Capture Backends

| Dimension | Microsoft Media Foundation (MSMF) | DirectShow (DSHOW) |
|---|---|---|
| **API Architecture** | Modern COM pipeline (Windows Vista through Windows 11) | Legacy COM filter graph (Windows 98 – Windows 7) |
| **Windows 11 Support** | **Primary Native Standard** | Deprecated / Compatibility mode |
| **High Resolution (4K+)** | Full hardware support (NV12, YUY2, MJPEG) | Frame-rate limited on high resolutions |
| **Hardware Acceleration** | Direct3D 11 / DXVA video processing | Software colorspace conversion |
| **CAMserv Role** | **Default Windows Backend (`cv2.CAP_MSMF`)** | **Fallback Compatibility Backend (`cv2.CAP_DSHOW`)** |

---

## 3. Optical Camera Enumeration & Probing

The `PlatformCameraBackend.enumerate_local_cameras()` contract discovers connected optical sensors without crashing when camera indices are absent:
- **Windows:** Probes video capture indices `0` through `3` using `cv2.CAP_MSMF`. Queries `CAP_PROP_FRAME_WIDTH`, `CAP_PROP_FRAME_HEIGHT`, and `CAP_PROP_FPS`.
- **Linux:** Scans `/dev/video*` character devices and correlates driver metadata via `/sys/class/video4linux/`.
- **Synthetic Fallback:** If zero physical cameras are connected, both backends emit an isolated `LocalCameraDevice(backend="synthetic")` descriptor, enabling test suites to run cleanly in headless CI environments.
