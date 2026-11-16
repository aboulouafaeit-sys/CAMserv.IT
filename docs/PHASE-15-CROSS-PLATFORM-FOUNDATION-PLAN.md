# Phase 15 Engineering Plan: Cross-Platform Architecture & Windows Foundation

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1` / `v1.0.0-LTS`  
**Author:** Principal Software Architect & Cross-Platform Systems Engineering Team  
**Pre-Requisite:** Phase 14 Release Candidate Qualification (Completed & Approved)  

---

## 1. Architectural Vision & Scope

Phase 15 transitions CAMserv from a Debian-exclusive appliance model into a unified, cross-platform enterprise security intelligence ecosystem. The architecture will natively support:
- **Primary Linux Appliance Targets:** Debian 13 (Trixie) and Debian 12 (Bookworm) on amd64 and arm64.
- **Primary Windows Target:** Windows 11 Enterprise / Pro (64-bit AMD64).
- **Secondary Windows Target:** Windows 10 (22H2) with strict security isolation boundaries.
- **Embedded Hardware:** Future CAMserv AI Edge Appliances (RK3588, Pi 5, Jetson Orin).

> **Core Constraint:** Windows Subsystem for Linux (WSL) is strictly prohibited as a substitute for native Windows validation. CAMserv must run natively as a native Windows process and Windows Service.

---

## 2. Directory Layout & Subsystem Boundaries

The codebase will be partitioned into three distinct tiers:

```text
src/camserv/
├── platform/
│   ├── shared/                   # 100% OS-Agnostic Core Application Logic
│   │   ├── engine.py             # Event loop, pipeline coordination, state machine
│   │   ├── config.py             # Unified environment & JSON configuration parser
│   │   ├── events.py             # Asynchronous pub/sub event bus
│   │   ├── credentials.py        # Abstract encrypted credential storage interface
│   │   ├── hardware_base.py      # Abstract hardware prober interface
│   │   └── logging.py            # Structured JSON audit logging (stdout/file)
│   ├── linux/                    # Linux / Debian Appliance Implementations
│   │   ├── service.py            # Systemd notification and watchdog integration
│   │   ├── camera_v4l2.py        # Linux Video4Linux2 (/dev/video*) backend
│   │   ├── gpu_vaapi.py          # Linux VAAPI / DRI / DRM hardware decoders
│   │   ├── permissions.py        # POSIX octal DAC permission enforcer (0750 / 0600)
│   │   └── hardware.py           # Sysfs thermal & CPU frequency prober
│   └── windows/                  # Native Microsoft Windows Implementations
│       ├── service.py            # Windows Service Control Manager (pywin32 / SCM)
│       ├── camera_mf.py          # Microsoft Media Foundation (MF) / DirectShow backend
│       ├── gpu_directml.py       # DirectX 12 / DirectML ONNX Runtime backend
│       ├── permissions.py        # Windows NTFS Access Control Lists (ACLs) & SDDL
│       ├── dpapi_vault.py        # Windows DPAPI machine-level secret encryption
│       └── hardware.py           # Windows WMI / CimInstance hardware telemetry
```

---

## 3. Subsystem Design & Platform Abstractions

### 3.1 Service Management & Background Execution
- **Linux:** Native `systemd` units (`camserv-core.service`, `camserv-ingestion.service`, etc.) running under unprivileged user `camserv:camserv` with cgroup v2 sandboxing.
- **Windows:** Native Windows Service registered via Windows Service Control Manager (SCM) executing under virtual service account `NT SERVICE\CAMserv` or `LOCAL SERVICE`, with interactive console mode available via CLI (`camserv serve`).

### 3.2 Camera Capture Abstraction
- **Shared:** RTSP and ONVIF protocol drivers remain 100% shared across both platforms using asynchronous socket transports.
- **Linux Optical Capture:** Native V4L2 device node polling (`/dev/video*`).
- **Windows Optical Capture:** Microsoft Media Foundation (MF) camera capture backend via DirectShow / OpenCV MSMF backend, supporting USB webcams and integrated laptop sensors.

### 3.3 Security, Permissions & Filesystem Access
- **Linux Filesystem Model:** POSIX DAC modes: `/etc/camserv` (0750), `/var/lib/camserv` (0750), `/etc/camserv/camserv.env` (0600).
- **Windows Filesystem Model:** Windows NTFS ACLs applied during installation:
  - Configuration directory (`%ProgramData%\CAMserv\config`): Read/Write to `SYSTEM` and `Administrators`; Read-Only to `NT SERVICE\CAMserv`.
  - Evidence vault (`%ProgramData%\CAMserv\vault`): Read/Write restricted to `SYSTEM` and `NT SERVICE\CAMserv`. Non-administrative users denied access.

### 3.4 Hardware Discovery & Inference Backends
- **Linux Inference:** ONNX Runtime with OpenVINO / TensorRT / RKNN / CPU Execution Providers.
- **Windows Inference:** ONNX Runtime with DirectML (DirectX 12) / CUDA / CPU Execution Providers, allowing edge hardware acceleration across Intel, AMD, and NVIDIA consumer and enterprise GPUs.

---

## 4. Phase 15 Implementation Stages & Milestones

| Stage | Milestone Description | Target Deliverables |
|---|---|---|
| **Stage 15.1** | Architecture Refactoring | Partition `src/camserv/platform/` into `shared`, `linux`, and `windows`. |
| **Stage 15.2** | Windows Camera Driver | Implement Microsoft Media Foundation (MSMF) camera capture backend. |
| **Stage 15.3** | Windows Service Wrapper | Implement Windows Service host with SCM lifecycle and event log hooks. |
| **Stage 15.4** | Windows NTFS & DPAPI | Implement NTFS ACL enforcer and Windows DPAPI master key vault. |
| **Stage 15.5** | Windows MSI / WiX Installer | Author automated WiX Toolset installer producing `camserv_setup.msi`. |
| **Stage 15.6** | Dual-Platform CI Matrix | Configure automated test runners validating both Debian Linux and Windows 11. |

---

## 5. Security & Risk Assessment

- **Windows 10 Lifecycle Risk:** Windows 10 reaches end of standard support in October 2025. All enterprise deployments will mandate Windows 11 Enterprise (22H2+). Windows 10 is supported strictly on a best-effort compatibility tier.
- **Credential Protection:** Windows DPAPI (`CryptProtectData`) will be used to protect the CAMserv master encryption key, binding secrets to the local machine security context without plaintext `.env` files.
