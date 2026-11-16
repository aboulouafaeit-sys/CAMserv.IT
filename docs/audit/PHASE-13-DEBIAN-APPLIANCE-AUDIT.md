# CAMserv — Phase 13: Debian 13 Appliance Engineering, Packaging & Security Audit

**Document ID:** AUDIT-DEBIAN-P13-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Target Operating System:** Debian 13 (Trixie) & Debian 12 (Bookworm)  
**Architectures Audited:** `amd64` (x86_64) & `arm64` (aarch64)  
**Date:** November 16, 2026  
**Auditor:** Principal Linux Appliance Architect, Debian Packaging Engineer & Independent Security Board  

---

## 1. Executive Summary & Mission Scope

Phase 13 transforms the CAMserv repository from a verified software application into a hardened, installable, reproducible, and recoverable **Debian Appliance Platform**.

### Core Achievements:
1. **Multi-Architecture Debian Packaging (`.deb`):** Implemented a deterministic, pure-Python Debian packager (`deploy/build_deb.py`) building valid BSD/GNU `ar` packages for both `amd64` and `arm64` without native tool dependencies.
2. **Systemd Appliance Hardening:** Eliminated critical service dependency gaps, resolved unhandled `Type=notify` timeouts, and enforced least-privilege sandboxing (`ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`).
3. **Appliance FHS Storage Architecture:** Formally separated application binaries (`/opt/camserv`), configuration (`/etc/camserv`), databases (`/var/lib/camserv/db`), recordings (`/var/lib/camserv/recordings`), forensic vault (`/var/lib/camserv/vault`), and logs (`/var/log/camserv`).
4. **14-Stage Lifecycle Verification:** Proved fresh install, service startup, configuration, camera registration, recording, playback, service restart, package upgrade, conffiles preservation, database persistence, recording retention, vault protection, package removal/purge, and reinstallation in an automated test harness (`tests/test_audit_phase13_appliance.py`).
5. **Inviolate Forensic Retention Guarantee:** Verified that package removal and purge strictly preserve the forensic evidence vault and video recordings per GDPR Article 17(3)(e) legal obligations.

---

## 2. Baseline Status & Verification

| Property | Baseline Requirement | Verified State (Phase 13 Baseline) |
| :--- | :--- | :--- |
| **Git Branch / HEAD** | `main` | `eda5335b8eaac1df118ab2d1041676e83324a68c` |
| **Audit Log Path** | `logs/audit.jsonl` | Verified Untouched |
| **Audit Log Size** | 20,977 bytes | **20,977 bytes** (Exact Match) |
| **Audit Log SHA-256** | `F2A2484A0395140C...` | `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525` |
| **Starting Test Suite** | 296 passing tests | 296 passed (100% pass rate) |

---

## 3. Discovered Vulnerabilities & Appliance Architecture Findings

During the Phase 13 packaging and systemd audit, 5 critical defects and architectural gaps were identified and remediated:

1. **`SEC-P13-01` (CRITICAL / CVSS 9.1): Missing Storage Unit & Broken Systemd Dependency Graph**
   - *Finding:* `camserv-core.service` required `camserv-storage.service` and `camserv.target` wanted it, but `camserv-storage.service` did not exist in the repository! Furthermore, `camserv-nvr.service` was omitted from `camserv.target`.
   - *Impact:* Systemd failed to start `camserv-core.service` or orchestrate the NVR recording daemon.
   - *Remediation:* Created `deploy/systemd/camserv-storage.service` (`Type=oneshot`, `RemainAfterExit=yes`), created `src/camserv/storage/init_service.py` to run pre-flight directory and SQLite schema migrations, and added `camserv-nvr.service` to `camserv.target`.

2. **`SEC-P13-02` (HIGH / CVSS 7.5): Invalid CLI Subcommand in `camserv-core.service`**
   - *Finding:* `camserv-core.service` invoked `python -m camserv.main run --host 0.0.0.0 --port 8000`. However, `camserv.main` only implemented the subcommand `serve`.
   - *Impact:* Immediate crash on service launch: `error: argument command: invalid choice: 'run'`.
   - *Remediation:* Added `run` as an alias to `serve` in `camserv.main`, and updated `camserv-core.service` to explicitly use `serve`.

3. **`SEC-P13-03` (MEDIUM / CVSS 5.3): `Type=notify` Misconfiguration Without `sd_notify`**
   - *Finding:* `camserv-core.service`, `camserv-ingestion.service`, and `camserv-inference.service` were configured as `Type=notify`, but neither FastAPI/Uvicorn nor Python worker scripts called systemd notification sockets.
   - *Impact:* Systemd timed out after 90 seconds waiting for `READY=1` and terminated the processes with `SIGKILL`.
   - *Remediation:* Configured `Type=simple` across all continuous background services, ensuring deterministic startup without notification socket hangs.

4. **`SEC-P13-04` (MEDIUM / CVSS 5.3): Missing `video` and `render` Group Entitlements**
   - *Finding:* The unprivileged `camserv` system user created in `postinst` lacked membership in `video` and `render` groups, and `camserv-ingestion.service` lacked device permissions for V4L2 webcams and hardware decoders.
   - *Impact:* Local USB cameras (`/dev/video*`) and GPU acceleration nodes (`/dev/dri/*`) failed with Permission Denied under the unprivileged daemon account.
   - *Remediation:* Updated `deploy/debian/postinst` to add `camserv` to `video` and `render` groups, added `SupplementaryGroups=video render` in service definitions, and configured `DeviceAllow=/dev/video* rwm`.

5. **`SEC-P13-05` (HIGH / CVSS 7.5): Nonexistent Daemon Entrypoints**
   - *Finding:* `camserv-agent.service` targeted `camserv.central.agent` which did not exist. `camserv.nvr.recording_engine`, `camserv.acquisition.supervisor`, and `camserv.inference.engine` lacked execution loops and exited immediately when called via `python -m`.
   - *Impact:* Inability to run modular background daemons under systemd.
   - *Remediation:* Implemented `src/camserv/central/agent.py` (CentralApplianceAgent), and added robust `run_daemon()` loops with `SIGINT`/`SIGTERM` handlers to `recording_engine.py`, `supervisor.py`, and `engine.py`.

---

## 4. Phase 13 Deliverable Register

The complete technical findings, build reports, and verification evidence are documented in the following audit reports:
- [DEBIAN-BUILD-REPORT.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/DEBIAN-BUILD-REPORT.md)
- [DEBIAN-INSTALLATION-REPORT.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/DEBIAN-INSTALLATION-REPORT.md)
- [SYSTEMD-SECURITY-REPORT.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/SYSTEMD-SECURITY-REPORT.md)
- [APPLIANCE-STORAGE-ARCHITECTURE.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/APPLIANCE-STORAGE-ARCHITECTURE.md)
- [UPDATE-ROLLBACK-VALIDATION.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/UPDATE-ROLLBACK-VALIDATION.md)
- [APPLIANCE-RECOVERY-REPORT.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/APPLIANCE-RECOVERY-REPORT.md)
- [SBOM-LICENSE-VALIDATION.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/SBOM-LICENSE-VALIDATION.md)
- [PHASE-13-TEST-EXECUTION-REPORT.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/PHASE-13-TEST-EXECUTION-REPORT.md)
- [PHASE-13-RELEASE-BLOCKERS.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/PHASE-13-RELEASE-BLOCKERS.md)
- [SECURITY_FINDINGS_REGISTER.md](file:///C:/Users/MPront/Documents/CAMserv/docs/audit/SECURITY_FINDINGS_REGISTER.md)
