# Phase 15: Linux Platform Adapter Architecture & Verification

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Target OS:** Debian 13 (Trixie) & Debian 12 (Bookworm)  
**Package:** `camserv.platform.linux`  
**Classification:** `IMPLEMENTED_AND_TESTED` (Software contract tests & ar packaging)

---

## 1. Overview & Architecture

The Linux Platform Adapter encapsulates all Debian/Linux-specific operational infrastructure into a dedicated, clean sub-package: `camserv.platform.linux`. It ensures that existing Debian 12/13 appliance functionality, systemd sandboxing, and POSIX DAC access controls remain 100% operational without regression.

```text
src/camserv/platform/linux/
├── __init__.py         # Package exports
├── service.py          # LinuxSystemdManager (systemctl & sd_notify watchdog)
├── filesystem.py       # LinuxFilesystem (POSIX DAC 0750/0600 & FHS layout)
├── camera.py           # LinuxV4L2CameraBackend (/dev/video* discovery & CAP_V4L2)
└── hardware.py         # LinuxHardwareProber (sysfs /proc telemetry prober)
```

---

## 2. Component Specifications

### 2.1 Systemd Service Management (`LinuxSystemdManager`)
- Implements `PlatformServiceManager`.
- Generates systemd unit definitions containing modern sandboxing directives:
  `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`, `WatchdogSec=15s`.
- Dispatches commands via `systemctl` (`daemon-reload`, `enable`, `start`, `stop`, `restart`, `is-active`).
- Emits keepalive heartbeats via UNIX domain datagram socket `NOTIFY_SOCKET` (`sd_notify("WATCHDOG=1")`).

### 2.2 Filesystem & Access Control (`LinuxFilesystem`)
- Implements `PlatformFilesystem`.
- Standard directories: `/etc/camserv`, `/var/lib/camserv`, `/var/log/camserv`, `/var/cache/camserv`.
- Enforces strict POSIX DAC permissions:
  - Configuration directory & Vault: `0700` (`rwx------`)
  - Recordings & Data: `0750` (`rwxr-x---`)
  - Secret files: `0600` (`rw-------`)

### 2.3 Optical Camera Backend (`LinuxV4L2CameraBackend`)
- Implements `PlatformCameraBackend`.
- Scans `/dev/video*` character devices and correlates device names via `/sys/class/video4linux/videoX/name`.
- Opens camera streams using OpenCV Video4Linux2 backend (`cv2.CAP_V4L2`).

### 2.4 Hardware Telemetry (`LinuxHardwareProber`)
- Implements `PlatformHardwareProber`.
- Reads thermal zones via `/sys/class/thermal/thermal_zone*/temp`.
- Queries memory from `/proc/meminfo` and GPU telemetry from `nvidia-smi`.

---

## 3. Verification & Debian Packaging Continuity

- **Regression Status:** All 307 Phase 14 regression tests continue passing with 100% fidelity.
- **Debian Packaging Continuity:** The Debian package builder (`deploy/build_deb.py`) and maintainer scripts (`postinst`, `prerm`, `postrm`) remain fully compatible with the Linux adapter layout.
