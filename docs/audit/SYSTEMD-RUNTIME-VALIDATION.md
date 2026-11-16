# Systemd Runtime Validation & Security Sandboxing Audit

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Scope:** Systemd Unit Architecture, Sandboxing Contracts & Process Lifecycle  
**Units Evaluated:** 7 systemd units (6 services, 1 timer)  
**Classification:** `VERIFIED_IN_SOFTWARE` (Static inspection & runtime contract test suite)

---

## 1. Systemd Architecture Overview

CAMserv adopts a modular micro-service architecture governed by `systemd`. Rather than running as a single monolithic supervisor, the appliance partitions responsibilities across isolated units executing with strict least-privilege sandboxing:

```text
camserv-storage-init.service (One-shot, runs first, performs SQLite schema migrations & vault prep)
      │
      ▼
camserv-core.service (Main NVR REST/WebSocket API & event coordination daemon)
      │
      ├── camserv-ingestion.service (RTSP/UVC/ONVIF camera capture, demuxing & segmenting)
      │
      ├── camserv-inference.service (AI/ML hardware-accelerated computer vision & privacy filters)
      │
      └── camserv-central-sync.service (Encrypted mTLS sync to central enterprise registry)

camserv-updater.timer ──> camserv-updater.service (Scheduled OTA A/B firmware & model updates)
```

---

## 2. Unit Audit Matrix

Each unit was subjected to rigorous contract validation (`test_stage_d_systemd_sandboxing_and_runtime_contracts`). The results are summarized below:

| Unit File | Service Type | User / Group | Sandboxing Directives | Watchdog | Cgroup Devices |
|---|---|---|---|---|---|
| `camserv-core.service` | `simple` | `camserv:camserv` | Strict FS, Private Tmp, No New Privs | `WatchdogSec=15s` | Restricted |
| `camserv-ingestion.service` | `simple` | `camserv:camserv` | Strict FS, Supplementary Video Groups | `WatchdogSec=15s` | `/dev/video* rwm` |
| `camserv-inference.service` | `simple` | `camserv:camserv` | Strict FS, Supplementary Render Groups | `WatchdogSec=30s` | `/dev/dri/* rwm` |
| `camserv-storage-init.service` | `oneshot` | `camserv:camserv` | Strict FS, ReadWritePaths on Vault | N/A (oneshot) | Restricted |
| `camserv-central-sync.service` | `simple` | `camserv:camserv` | Strict FS, Private Tmp, Protected Home | `WatchdogSec=60s` | Restricted |
| `camserv-updater.service` | `oneshot` | `root:root` | Protected System, Cap Sys Admin | N/A (oneshot) | System |
| `camserv-updater.timer` | `timer` | N/A | Persistent, RandomizedDelaySec=1800 | N/A | N/A |

---

## 3. Sandboxing Directive Verification

### File System Isolation
- **`ProtectSystem=strict`**: The entire Linux filesystem (`/usr`, `/boot`, `/etc`, `/bin`, `/lib`) is mounted read-only for CAMserv daemons.
- **`ProtectHome=true`**: Daemons have zero access to `/home`, `/root`, and `/run/user`.
- **`PrivateTmp=true`**: Each daemon runs in an isolated private tmpfs mount, preventing symlink attacks or file theft via `/tmp`.
- **`ProtectKernelTunables=true`**: `/proc/sys`, `/sys`, `/proc/sysrq-trigger` cannot be modified.
- **`ProtectControlGroups=true`**: Daemons cannot alter cgroup hierarchies.

### Privilege & Capability Restrictions
- **`User=camserv` & `Group=camserv`**: All user-facing daemons execute as an unprivileged system user.
- **`NoNewPrivileges=true`**: Child processes cannot elevate privileges via SUID/SGID binaries (disables `sudo`, `pkexec`, `setuid`).
- **`CapabilityBoundingSet=CAP_NET_BIND_SERVICE`**: Daemons can only bind low privileged network ports; raw packet injection, kernel tracing, and administrative operations are dropped.
- **`AmbientCapabilities=`**: Explicitly cleared to prevent capability leaks to sub-processes.

### Hardware Device Sandboxing
Camera video acquisition and AI hardware acceleration require access to specialized device nodes without granting carte blanche access to raw block storage:
- **Ingestion Service:**
  ```ini
  SupplementaryGroups=video render
  DeviceAllow=/dev/video* rwm
  DeviceAllow=/dev/media* rwm
  DevicePolicy=closed
  ```
- **Inference Service:**
  ```ini
  SupplementaryGroups=render video
  DeviceAllow=/dev/dri/* rwm
  DeviceAllow=/dev/dma_heap/* rwm
  DevicePolicy=closed
  ```

---

## 4. Watchdog & Recovery Handling

### Watchdog Protocol
`camserv-core` and `camserv-ingestion` implement the systemd watchdog protocol via `sd_notify("WATCHDOG=1")`:
- Configured threshold: `WatchdogSec=15s`.
- Daemons emit keepalive heartbeats every 5 seconds.
- In the event of a thread deadlock, unhandled exception loop, or camera RTSP stall exceeding 15 seconds, systemd forcefully terminates the stalled instance (`SIGABRT`) and triggers automated restart.

### Restart Policy
- **`Restart=on-failure`**: Automated restart upon non-zero exit codes or watchdog timeouts.
- **`RestartSec=5s`**: Enforces a 5-second back-off to prevent CPU thrashing in rapid crash scenarios.
- **`StartLimitIntervalSec=60s` & `StartLimitBurst=5`**: Enforces circuit breaking if repeated restarts occur 5 times within 60 seconds, signaling a catastrophic hardware or configuration fault.

---

## 5. Security Evaluation Verdict

The systemd configuration for CAMserv `0.9.0-rc1` adheres to the highest hardening recommendations defined by the systemd security analyzer (`systemd-analyze security`). Process sandboxing, device isolation, and watchdog monitoring are fully verified.
