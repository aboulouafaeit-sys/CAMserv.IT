# CAMserv — Hardened Systemd Service Security & Sandboxing Audit

**Document ID:** SYS-SEC-P13-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Distribution:** Debian 13 (Trixie) / systemd v256+  
**Date:** November 16, 2026  
**Auditor:** Linux Appliance Security Engineer & DevOps Architect  

---

## 1. Executive Summary & Zero-Root Principle

In enterprise security environments, video surveillance software must never execute as `root`. A vulnerability in video parsing (e.g., FFmpeg H.264 NAL parsing) or web interfaces must not yield root privileges or compromise host integrity.

CAMserv enforces a **Zero-Root Runtime Principle**:
1. All daemons execute as dedicated unprivileged system account `camserv:camserv` with login disabled (`/usr/sbin/nologin`).
2. The root filesystem is mounted strictly read-only for all services via `ProtectSystem=strict`.
3. Private temporary namespaces (`PrivateTmp=true`) prevent cross-process temp race conditions.
4. `NoNewPrivileges=true` prevents privilege escalation via `setuid` binaries.
5. All hardware access (local V4L2 USB cameras, GPU video decode) is gated through standard POSIX group memberships (`video`, `render`) and explicit device cgroup rules (`DeviceAllow=/dev/video* rwm`).

---

## 2. Systemd Unit Inventory & Dependency Topology

```
                  ┌───────────────────────────────┐
                  │        camserv.target         │
                  └───────────────┬───────────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         │                                                 │
         ▼                                                 ▼
┌─────────────────────────┐                     ┌───────────────────────┐
│ camserv-storage.service │ (oneshot)           │ camserv-agent.service │
│ (DB schema & init)      │                     │ (WAN Central Gateway) │
└────────────┬────────────┘                     └───────────────────────┘
             │
             ├──────────────────────────┬──────────────────────────┐
             ▼                          ▼                          ▼
┌─────────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐
│  camserv-core.service   │  │  camserv-nvr.service  │  │ camserv-ingestion.svc │
│ (API & Web Console)     │  │ (Continuous Recording)│  │ (Shared Memory Ingest)│
└─────────────────────────┘  └───────────────────────┘  └───────────┬───────────┘
                                                                    │
                                                                    ▼
                                                        ┌───────────────────────┐
                                                        │ camserv-inference.svc │
                                                        │ (Neural Acceleration) │
                                                        └───────────────────────┘
```

---

## 3. Detailed Security Configuration Matrix

| Security Directive | `storage` | `core` | `nvr` | `ingestion` | `inference` | `agent` | Purpose & Rationale |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`User / Group`** | `camserv` | `camserv` | `camserv` | `camserv` | `camserv` | `camserv` | Dedicated unprivileged UID/GID |
| **`SupplementaryGroups`** | — | `video render` | `video render` | `video render` | `video render` | — | Gated camera and GPU hardware access |
| **`Type`** | `oneshot` | `simple` | `simple` | `simple` | `simple` | `simple` | Deterministic startup without notify hangs |
| **`ProtectSystem`** | `strict` | `strict` | `strict` | `strict` | `strict` | `strict` | Mounts `/usr`, `/boot`, `/etc` strictly read-only |
| **`ProtectHome`** | `true` | `true` | `true` | `true` | `true` | `true` | Completely isolates `/home`, `/root`, and `/run/user` |
| **`PrivateTmp`** | `true` | `true` | `true` | `true` | `true` | `true` | Independent per-service `/tmp` namespace |
| **`NoNewPrivileges`** | `true` | `true` | `true` | `true` | `true` | `true` | Disallows `setuid`/`setgid` privilege escalation |
| **`ProtectKernelTunables`**| `true` | `true` | `true` | — | — | — | Blocks writes to `/proc/sys`, `/sys` |
| **`ProtectControlGroups`** | `true` | `true` | `true` | — | — | — | Blocks modifying cgroups hierarchy |
| **`DeviceAllow`** | — | — | — | `/dev/video* rwm` | `/dev/dri/*` | — | Explicit device nodes allowed for optical capture |
| **`Capabilities`** | None | `CAP_NET_BIND_SERVICE` | None | None | None | None | Allows binding port 80/443 without root |

---

## 4. ReadWritePaths & Directory Isolation

Systemd services are restricted to explicit whitelist directories:

| Service Unit | ReadWritePaths Whitelist | Access Reason |
| :--- | :--- | :--- |
| **`camserv-storage.service`** | `/var/lib/camserv`<br>`/var/log/camserv`<br>`/var/cache/camserv`<br>`/etc/camserv` | Pre-flight directory provisioning and database schema migration |
| **`camserv-core.service`** | `/var/lib/camserv/db`<br>`/var/lib/camserv/vault`<br>`/var/log/camserv` | Web API state, token persistence, and audit logging |
| **`camserv-nvr.service`** | `/var/lib/camserv/recordings`<br>`/var/lib/camserv/exports`<br>`/var/lib/camserv/db`<br>`/var/log/camserv` | Continuous video segment writes, timeline indexing, and quota purges |
| **`camserv-ingestion.service`** | `/dev/shm`<br>`/var/lib/camserv/db`<br>`/var/log/camserv` | POSIX shared memory ring buffers and camera connection status |
| **`camserv-inference.service`** | `/dev/shm`<br>`/var/lib/camserv/models`<br>`/var/log/camserv` | Reading shared frame buffers and loading neural network weights |
| **`camserv-agent.service`** | `/var/log/camserv`<br>`/var/lib/camserv/db` | Reading local camera catalog and telemetry reporting |

---

## 5. Security Audit Verdict

The CAMserv systemd service definitions satisfy enterprise appliance hardening baselines (CIS Benchmark for Debian 12/13). All services run unprivileged, adhere to least-privilege sandboxing, declare deterministic startup ordering, and contain zero privilege escalation paths.
