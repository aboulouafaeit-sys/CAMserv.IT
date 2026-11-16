# Phase 15: Cross-Platform Architecture Specification

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1` (Cross-Platform Foundation)  
**Author:** Principal Cross-Platform Systems Architect  
**Scope:** Architecture Decomposition, Subsystem Boundaries & Interface Contracts  

---

## 1. Architectural Vision: One Core, Dual Platform Adapters

CAMserv is engineered as a unified security intelligence platform. Rather than maintaining separate codebases for Debian Linux and Microsoft Windows, the architecture strictly decouples platform-agnostic business logic from operating-system-specific infrastructure:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                             CAMserv Shared Core Engine                      │
│                                                                             │
│  - Application Lifecycle & CLI (camserv.main)                               │
│  - Camera Ingestion Engine & Decoupled Buffering (camserv.acquisition)     │
│  - NVR Segment Recording & Timeline Indexing (camserv.nvr)                  │
│  - Fail-Closed Privacy & Masking Pipeline (camserv.inference.privacy)       │
│  - Computer Vision & Behavioral Threat Engine (camserv.events)              │
│  - Ed25519 Digital Forensics & Evidence Vault (camserv.storage.forensics)   │
│  - SQLite WAL Database & Schema Migrations (camserv.storage)                │
│  - Central Fleet Multi-Site Synchronization (camserv.central)               │
│  - REST & WebSocket Management APIs (camserv.api)                           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                      Platform Adapter Interfaces (ABCs)
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────────────────────┐ ┌───────────────────────────────────────┐
│     Linux Platform Adapter (Debian)   │ │    Windows Platform Adapter (Win11)   │
│                                       │ │                                       │
│ - Systemd Units & sd_notify watchdog  │ │ - Windows Service Control Manager (SCM│
│ - POSIX DAC Permissions (0750/0600)   │ │ - Windows NTFS Access Control Lists   │
│ - FHS Paths (/var/lib, /etc/camserv)  │ │ - Windows Standard Paths (%ProgramData│
│ - Linux V4L2 Device Nodes (/dev/video)│ │ - Media Foundation Camera (CAP_MSMF)  │
│ - Sysfs / Proc Hardware Probing       │ │ - Win32 DPAPI Key Vault (crypt32.dll) │
│ - Cgroups v2 Resource Hardening       │ │ - DirectML / DirectX 12 Acceleration  │
└───────────────────────────────────────┘ └───────────────────────────────────────┘
```

---

## 2. Directory Layout & Module Boundaries

The implementation establishes a clean abstraction layer under `src/camserv/platform/`:

```text
src/camserv/platform/
├── __init__.py                     # Exposes platform factory and active profile
├── factory.py                      # Dynamic platform adapter factory (auto-detects OS)
├── shared/                         # 100% OS-Agnostic Interface Definitions & Paths
│   ├── __init__.py
│   ├── interfaces.py               # Abstract Base Classes (ABCs) for platform contracts
│   ├── paths.py                    # Cross-platform filesystem path resolver
│   └── credentials.py             # Base encrypted credential vault abstractions
├── linux/                          # Debian 12 / 13 Appliance Implementation
│   ├── __init__.py
│   ├── service.py                  # Systemd service manager & watchdog client
│   ├── filesystem.py               # POSIX DAC permission enforcer & FHS directory manager
│   ├── camera.py                   # V4L2 optical device discovery & capture backend
│   └── hardware.py                 # Linux sysfs / procfs hardware telemetry prober
└── windows/                        # Windows 11 / Windows 10 Implementation
    ├── __init__.py
    ├── service.py                  # Windows Service Control Manager & service host
    ├── filesystem.py               # %ProgramData% manager & Windows NTFS ACL enforcer
    ├── camera.py                   # Microsoft Media Foundation / DirectShow camera backend
    ├── credentials.py              # Windows DPAPI machine-level secret encryption
    ├── firewall.py                 # Windows Defender Firewall rule manager
    └── hardware.py                 # Windows WMI / CimInstance hardware telemetry prober
```

---

## 3. Platform Abstraction Interface Contracts

Every platform-specific operation implements an explicit Python Abstract Base Class (ABC) defined in `src/camserv/platform/shared/interfaces.py`:

### 3.1 Service Management Contract (`PlatformServiceManager`)
- `install_service(name, display_name, description, exec_path, args, dependencies)`
- `uninstall_service(name)`
- `start_service(name)`
- `stop_service(name, timeout_sec)`
- `restart_service(name)`
- `query_status(name) -> ServiceStatus`
- `emit_watchdog_heartbeat()`

### 3.2 Filesystem & Path Contract (`PlatformFilesystem`)
- `get_config_dir() -> Path`
- `get_data_dir() -> Path`
- `get_recordings_dir() -> Path`
- `get_vault_dir() -> Path`
- `get_log_dir() -> Path`
- `secure_directory(path: Path, is_sensitive: bool) -> bool`
- `secure_file(path: Path, is_secret: bool) -> bool`

### 3.3 Credential Protection Contract (`PlatformCredentialVault`)
- `protect_secret(secret_bytes: bytes, description: str) -> bytes`
- `unprotect_secret(encrypted_bytes: bytes) -> bytes`
- `is_hardware_bound() -> bool`

### 3.4 Camera Acquisition Contract (`PlatformCameraBackend`)
- `enumerate_local_cameras() -> list[LocalCameraDevice]`
- `open_capture_stream(device_index_or_path, width, height, fps) -> Any`
- `get_backend_name() -> str`

### 3.5 Hardware Telemetry Contract (`PlatformHardwareProber`)
- `probe_system_metrics() -> dict[str, Any]`
- `probe_gpu_metrics() -> list[dict[str, Any]]`
- `probe_thermal_status() -> dict[str, Any]`
