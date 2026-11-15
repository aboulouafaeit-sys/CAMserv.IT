# CAMserv AI Appliance & Edge OS Architecture

**Document ID:** ARCH-APPLIANCE-2026-001  
**Classification:** Embedded Systems & Operating Platform Specification  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Operating Environment and Target Hardware

The **CAMserv AI Appliance** is a hardened, turnkey hardware platform engineered to provide reliable 24/7 video processing and recording in demanding physical environments (industrial edge, remote substations, enterprise server rooms).

### Supported Hardware Tiers:
- **Tier 1 (Entry Edge Node):** Quad-core ARM64 or x86_64, 4GB RAM, integrated NPU (e.g., Coral Edge TPU, RK3588, Hailo-8). Sized for 1 to 4 camera streams.
- **Tier 2 (Commercial Appliance):** 8-core x86_64 CPU, 16GB ECC RAM, discrete GPU (NVIDIA RTX / Intel Arc), 2TB NVMe SSD. Sized for 8 to 16 camera streams.
- **Tier 3 (Enterprise Server / Appliance):** 16+ core AMD EPYC / Intel Xeon, 64GB ECC RAM, dual NVIDIA L4 GPUs, hardware RAID NVMe pool. Sized for 32 to 64 camera streams.

---

## 2. Linux OS Hardening & Partitioning Blueprint

The appliance runs a stripped, immutable Debian 12 (Bookworm) LTS derivative configured according to CIS Level 2 Linux benchmarks:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Appliance Disk Layout                           │
├────────────┬─────────────┬─────────────┬──────────────┬────────────────┤
│ EFI Boot   │ Root Slot A │ Root Slot B │ Var / Data   │ Evidence Vault │
│ (1024 MB)  │ (Read-Only) │ (Read-Only) │ (Ext4/ZFS)   │ (Encrypted)    │
│ FAT32      │ (16 GB)     │ (16 GB)     │ (NVMe Pool)  │ (LUKS2 WORM)   │
└────────────┴─────────────┴─────────────┴──────────────┴────────────────┘
```

- **Dual A/B System Slots:** Updates are applied to the inactive slot (`Root Slot B` while running on `A`). If post-boot health checks fail, the bootloader automatically rolls back to the known-good partition.
- **Read-Only Root Filesystem:** Root filesystems are mounted read-only using `overlayfs` for ephemeral runtime modifications.
- **Kernel Hardening (`sysctl-hardening.conf`):** ASLR enabled, SYN flood protection active, ICMP redirects disabled, core dumps disabled, and ptrace scoping enforced.

---

## 3. Sandboxed systemd Service Hierarchy

All CAMserv platform processes run under dedicated non-root service accounts (`camserv:camserv`) with restricted Linux capabilities:

- `camserv-ingestion.service`: Manages camera RTSP stream decoders and shared memory ring buffers. Sandboxed with `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`.
- `camserv-inference.service`: Executes neural network inference and tracking. Access restricted strictly to `/dev/dri/` and `/dev/nvhost*` accelerator devices.
- `camserv-core.service`: Handles business logic, event evaluation, NVR recording, and SQLite persistence. `ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=yes`.
- `camserv-agent.service`: Coordinates telemetry heartbeats and remote OTA management with CAMserv Central.
- `camserv.target`: Synchronization target coordinating multi-service startup ordering and graceful shutdown sequences.

---

## 4. Hardware Watchdog & Thermal Protection

- **Hardware Watchdog:** Integrated with Linux `/dev/watchdog` (`systemd-watchdog`). The core service must ping the watchdog every 15 seconds; an unresponsive service triggers an automated controlled service restart.
- **Thermal Adaptive Throttling (`camserv.platform.tiers`):** If GPU/CPU die temperatures exceed $85^\circ\text{C}$, the adaptive scheduler automatically decimates background frame rates and disables non-critical analytics to prevent hardware degradation.
