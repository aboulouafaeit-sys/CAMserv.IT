# ADR-013: Cross-Platform Windows & Linux Architecture Abstraction

## Status
Proposed / Approved for Phase 15 Foundation

## Context
CAMserv has established its Linux appliance deployment model on Debian 13 (Trixie) and Debian 12 (Bookworm) with systemd, cgroup sandboxing, and V4L2 device integration. However, enterprise security operations centers, corporate workstations, and system integrators frequently mandate native Microsoft Windows execution without reliance on virtual machines or WSL.

To support both Linux appliance hardware (Debian 12/13, Rockchip RK3588, Raspberry Pi 5) and Windows environments (Windows 11 Enterprise primary target, Windows 10 assessed compatibility) without duplicating application logic or fragmenting codebases, CAMserv requires an architectural abstraction layer separating shared core logic from operating-system-specific services.

## Decision
1. **Decouple Core from OS Subsystems:**
   Establish explicit package boundaries:
   - `camserv.platform.shared`: OS-agnostic core engine, async pipelines, streaming gateway, REST/WebSocket APIs, SQLite WAL data layers, and Ed25519 forensics.
   - `camserv.platform.linux`: Linux-specific systemd unit management, cgroups v2 resource quotas, `/dev/video*` V4L2 capture, `/dev/dri/*` VAAPI/DRM GPU decoding, and POSIX DAC permissions (`0750` / `0600`).
   - `camserv.platform.windows`: Windows Service host architecture (`pywin32` / Windows Service Control Manager), Microsoft Media Foundation (MF) / DirectShow optical capture, DirectX 12 / DirectML GPU acceleration, Windows DPAPI credential encryption, and NTFS Access Control Lists (ACLs).

2. **Unified Data and Evidence Formats:**
   All SQLite database schemas, chunked MP4 recordings, Ed25519 signature formats, and JSON manifests remain 100% identical and byte-for-byte interchangeable between Linux and Windows.

3. **Operating System Priority & Governance:**
   - **Debian 13 Trixie & Debian 12 Bookworm:** Primary appliance target.
   - **Windows 11 (22H2+):** Primary commercial workstation/server target.
   - **Windows 10 (22H2):** Secondary target with documented security lifecycle assessment (EOL October 2025 considerations).
   - **WSL:** Prohibited as proof of native Windows compatibility.

## Consequences
- **Positive:** True cross-platform operation; seamless portability of recordings and forensic vaults; ability to run as a native Windows Service without WSL overhead.
- **Negative:** Requires maintaining dual service wrappers (systemd vs Windows SCM) and testing dual camera capture pipelines (V4L2 vs Media Foundation).
