# CAMserv — Phase 3 Operating Environment & Deployment Architecture

**Document ID:** ARCH-DEPLOY-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Stage 2 Deliverable  
**Date:** November 15, 2026  
**Status:** PRODUCTION OS & DEPLOYMENT BLUEPRINT  
**Author / Authority:** Embedded Linux Engineer, DevOps & Release Engineer & Principal Systems Engineer  

---

## 1. Executive Summary & Design Scope

The **CAMserv Operating Environment** provides a hardened, immutable, turnkey Linux deployment platform for dedicated **CAMserv AI Appliances** and enterprise servers.

Surveillance appliances in mission-critical facilities must operate autonomously without manual sysadmin intervention, survive sudden ungraceful power outages without filesystem corruption, resist network intrusion attempts, and prevent service crash loops from exhausting device resources.

### Architectural Invariants:
1. **Developer Workstation Isolation:** The deployment architecture is self-contained. At no point during development or CI does CAMserv touch, alter, or reconfigure the host developer's personal operating system, EFI partition, or bootloader.
2. **Immutable Read-Only Root Filesystem:** The root operating system is mounted read-only (`ro`), utilizing `overlayfs` for volatile runtime modifications. System binary corruption is mathematically prevented across unexpected power loss.
3. **Partitioned Evidence Preservation:** Operational databases (`/data/db`) and forensic video vaults (`/data/vault`) reside on dedicated persistent partitions with strict `noatime,nodev,nosuid` mount options. Recovery procedures **never** delete user evidence.
4. **Supervised Service Tree with Circuit Breakers:** Services run in dedicated unprivileged systemd sandboxes with hardware watchdog heartbeats and exponential backoff restart policies, preventing endless restart loops.

---

## 2. Base Operating System Evaluation

| Linux Distribution Foundation | Long-Term Support (LTS) | Kernel & Driver Modernity | Package Availability | Video Acceleration (VAAPI/NVDEC) | Embedded Footprint | Suitability Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Debian 12 "Bookworm" Minimal** | 5 Years (LTS) | Linux 6.1 LTS (Rock-solid stability) | Debian Apt ecosystem | Excellent (mesa-va-drivers, non-free NVIDIA) | $\sim 850\text{ MB}$ base | **PRIMARY CHOICE (Tier 1 Appliances)** |
| **Ubuntu 24.04 "Noble Numbat" LTS** | 5 + 5 Years (Ubuntu Pro) | Linux 6.8 LTS (Modern hardware support) | Canonical PPA + Apt | Pre-packaged NVIDIA CUDA/TensorRT | $\sim 1.2\text{ GB}$ base | **RECOMMENDED FOR ENTERPRISE (Tier 2/3)** |
| **Alpine Linux (musl libc)** | 2 Years | Linux 6.6 LTS | apk package manager | Incompatible with proprietary CUDA/ONNX | $\sim 150\text{ MB}$ | **REJECTED (C++ ONNX & CUDA compatibility issues)** |
| **Yocto / Buildroot Custom Linux** | Custom | Custom Embedded | High maintenance overhead | High engineering maintenance cost | $< 300\text{ MB}$ | **RESERVED FOR FUTURE OEM SILICON** |

**Selection Decision:**  
CAMserv appliances standardize on **Debian 12 Minimal** for Profile A (Edge) and **Ubuntu 24.04 LTS Minimal** for Profiles B (Professional) and C (Enterprise) due to native proprietary driver compatibility, five-year security maintenance, and robust Debian packaging.

---

## 3. Storage Layout & Partitioning Architecture

The appliance disk layout (defined in `deploy/appliance-os/partitioning.yaml`) enforces dual-slot A/B system partitions and isolated data storage:

```
+---------------------------------------------------------------------------------+
|                        PHYSICAL APPLIANCE NVMe / DISK                           |
+--------+------------------+------------------+----------------+-----------------+
|  EFI   |   SYSTEM_A (16G) |   SYSTEM_B (16G) |  DATA_DB (32G) | VAULT_EVIDENCE  |
| (512M) | Active Read-Only | Inactive Slot    | Persistent WAL | (Remaining GB)  |
| /boot  | Root (overlayfs) | OTA Target       | /data/db       | /data/vault     |
+--------+------------------+------------------+----------------+-----------------+
```

### Mount Points & Filesystem Flags:
* `/boot/efi`: `vfat`, `ro` after boot (mounted `rw` only during signed EFI updates).
* `/`: `ext4`, `ro,noatime,errors=remount-ro`. Protected against tampering and write exhaustion.
* `/data/db`: `ext4`, `rw,noatime,nodev,nosuid`. Dedicated to SQLite WAL files and manifest indices.
* `/data/vault`: `ext4` or `xfs`, `rw,noatime,nodev,nosuid,allocsize=64m`. High-throughput sequential write pool for encrypted video chunks and Ed25519 signatures.

---

## 4. Supervised Service Architecture & Systemd Units

CAMserv defines an unbundled, process-isolated service tree governed by `deploy/systemd/camserv.target`:

```
                           +────────────────────+
                           |   camserv.target   |
                           +─────────┬──────────+
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
+─────────────────+         +─────────────────+         +─────────────────+
| camserv-storage |         |camserv-ingestion|         |camserv-inference|
| (SQLite & Vault)|         | (Isolated Dec)  |         | (ONNX & Tensor) |
+────────┬────────+         +────────┬────────+         +────────┬────────+
         │                           │                           │
         └─────────────┬─────────────┴─────────────┬─────────────┘
                       ▼                           ▼
              +─────────────────+         +─────────────────+
              |  camserv-core   |         |  camserv-agent  |
              | (Orchestrator)  |         | (mTLS Central)  |
              +─────────────────+         +─────────────────+
```

### 4.1 Systemd Security Sandboxing
Every service unit mandates strict Linux kernel namespace isolation:
* `ProtectSystem=strict`: The entire OS filesystem is mounted read-only for the process.
* `ProtectHome=true`: User home directories are inaccessible.
* `NoNewPrivileges=true`: SUID/SGID privilege escalation is disabled.
* `PrivateTmp=true`: Isolated process `/tmp` preventing symlink attacks.
* `ReadWritePaths=`: Explicitly whitelisted writable paths (`/data/db`, `/data/vault`, `/var/log/camserv`, `/dev/shm`).

### 4.2 Watchdog Monitoring & Circuit Breaking
Integrated via `src/camserv/deploy/supervisor.py`:
* **Heartbeat Period:** Every 15 seconds (`WatchdogSec=15s`).
* **Deadman Detection:** If a worker deadlocks or freezes for $> 30\text{s}$, systemd sends `SIGABRT` to generate a stack trace, terminates the PID, and restarts the service.
* **Circuit Breaker:** If a service crashes $\ge 5$ times within 60 seconds, the supervisor trips the circuit breaker (`CIRCUIT_BROKEN`), halting restart loops to prevent cascading I/O death, and triggers a critical operator alert.

---

## 5. Linux Kernel Security Hardening (`sysctl`)

Applied at boot via `deploy/appliance-os/sysctl-hardening.conf`:
1. **Memory Protection:** Full ASLR (`kernel.randomize_va_space = 2`), protected symlinks/FIFOs (`fs.protected_symlinks = 1`).
2. **Network Attack Mitigation:** TCP SYN cookies enabled (`net.ipv4.tcp_syncookies = 1`), reverse-path filtering enabled (`rp_filter = 1`), ICMP redirect acceptance disabled.
3. **High-Throughput Streaming Tuning:** Shared memory maximum raised to 16GB (`kernel.shmmax = 17179869184`), socket receive buffers tuned to 16MB (`net.core.rmem_max = 16777216`).

---

## 6. Disaster Recovery & Snapshot Architecture

Managed by `DisasterRecoveryManager` in `src/camserv/deploy/supervisor.py`:
* **Atomic Pre-Update Backup:** Prior to any software update or schema migration, the configuration and database headers are snapshotted to `/data/backup/`.
* **Non-Destructive Recovery Audit:** In the event of an unexpected reboot, `safe_recovery_audit` verifies that `/data/vault` retains all encrypted chunks, SQLite WAL files are intact, and evidence integrity remains unbroken.
* **Rollback Trigger:** If post-update health checks fail within 120 seconds, the appliance automatically switches boot slots back to the previous verified release.

---

## 7. Stage 2 Acceptance Verdict

$$\mathbf{STAGE\_2\_ACCEPTANCE\_VERDICT: \quad ACCEPTED}$$

All deliverables for Stage 2 (Operating Environment & Deployment Architecture) are implemented, verified by 5 unit tests in `tests/test_deploy_environment.py`, and documented.
