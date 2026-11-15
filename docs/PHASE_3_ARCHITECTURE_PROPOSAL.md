# CAMserv — Phase 3 Master Architecture Proposal

**Document ID:** ARCH-PROP-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 — Enterprise Infrastructure, AI Appliance & Distributed Management  
**Date:** November 15, 2026  
**Status:** ARCHITECTURAL SPECIFICATION & BLUEPRINT  
**Target Baseline Commit:** `b52c4915d3f3c30c64ef2162aa5c4beb92f836ea`  
**Author / Authority:** Chief Software Architect, Enterprise Infrastructure Architect & Principal Systems Engineer  

---

## 1. Executive Summary & Architectural Vision

The mission of **Phase 3** is to evolve CAMserv from a single-node computer vision platform into an enterprise-grade, distributed, hardware-independent security intelligence product ecosystem. 

CAMserv will be engineered to power three primary deployment modes:
1. **CAMserv Core:** The standalone local edge intelligence engine running on heterogeneous on-premise hardware (from low-power edge CPUs up to enterprise GPU servers).
2. **CAMserv AI Appliance:** Purpose-engineered dedicated hardware appliances (Edge, Professional, Enterprise) running a hardened, turnkey Linux operating environment with automated service supervision and crash recovery.
3. **CAMserv Central & Enterprise:** A multi-site, multi-tenant fleet management plane that securely coordinates, monitors, updates, and audits hundreds of distributed CAMserv nodes over encrypted zero-trust connections without centralizing bulk video streams.

---

## 2. Product Family Architecture

```
+═════════════════════════════════════════════════════════════════════════════════+
║                         CAMserv Central & Enterprise                            ║
║     (Central Fleet Dashboard, Multi-Site RBAC, Global Audit, OTA Dispatcher)     ║
+═════════════════════════════════════════════════════════════════════════════════+
          ▲                                  ▲                                  ▲
          │ mTLS (Mutual TLS v1.3)           │ Encrypted WebSockets             │ Signed OTA
          │ Telemetry & Manifest Digests     │ Low-Bandwidth Event Alerts       │ Update Packages
          ▼                                  ▼                                  ▼
+──────────────────────────+     +──────────────────────────+     +──────────────────────────+
|  CAMserv AI Appliance    |     |  CAMserv AI Appliance    |     |  CAMserv Edge Node       |
|  Profile C: Enterprise   |     |  Profile B: Professional |     |  Profile A: Edge         |
|  - Multi-Camera Cluster  |     |  - On-Premise NVR Form   |     |  - Compact ARM / x86     |
|  - Dedicated Accelerators|     |  - Hardware Decoding     |     |  - CPU / iGPU Inference  |
|  - Hardware WORM Vault   |     |  - Local Operator HUD    |     |  - Local Fail-Closed Mask|
+──────────────────────────+     +──────────────────────────+     +──────────────────────────+
          │                                  │                                  │
          ▼                                  ▼                                  ▼
 [IP Cameras: Site Alpha]           [IP Cameras: Site Beta]            [IP Cameras: Gate Remote]
```

### 2.1 The Eight Product Family Pillars
1. **CAMserv Core:** The high-throughput video ingestion, neural inference, ByteTrack multi-object tracking, and fail-closed privacy pipeline.
2. **CAMserv AI Appliance:** Dedicated turnkey physical appliance designs with pre-configured operating environments, thermal monitoring, and hardware watchdogs.
3. **CAMserv Central:** Centralized management console for managing remote device fleets, health telemetry, and global security policies across physical sites.
4. **CAMserv Edge:** Lightweight distributed sensor nodes optimized for low-power edge gateways and remote perimeter cameras.
5. **CAMserv Enterprise:** Clustered multi-node deployment supporting multi-tenancy, cross-site identity (SSO/SAML), and high-availability database replication.
6. **CAMserv Operator Interface:** Unified 14-screen glassmorphic desktop and web interface for live video walls, event triage, and human-in-the-loop review.
7. **CAMserv Update Infrastructure:** Secure TUF/Ed25519-signed over-the-air update system with automated A/B partition and database rollback.
8. **CAMserv Deployment System:** Fully automated, reproducible deployment toolchain delivering Debian/Ubuntu LTS ISO images, Docker Compose orchestration, and systemd service units.

---

## 3. Non-Negotiable Core Engineering Invariants

1. **Hardware Independence & Agnostic Operation:**
   - CAMserv must run reliably on CPU-only machines, integrated GPUs (Intel/AMD), discrete NVIDIA GPUs, ARM64 SoCs, and dedicated edge NPUs.
   - Hardware detection must be autonomous, reporting capability profiles without hardcoding specific GPU models.
   - A missing optional accelerator must trigger graceful workload degradation, never a fatal crash.
2. **Preservation of Phase 1 and Phase 2 Baselines:**
   - Zero rewrites of functioning components: Process-isolated camera ingestion (`CameraWorkerSupervisor`), zero-copy shared memory (`/dev/shm`), `ModelRegistry`, `CentralizedPrivacyEnforcer`, `BehavioralEngine`, and `SQLiteStore` must remain intact.
   - 100% backward compatibility of configuration and database schemas.
3. **Fail-Closed Privacy Guarantee (GDPR Art. 25):**
   - No code path in production profiles permits unmasked raw video to reach operator screens, public streams, or remote central consoles.
   - Detection failure mathematically triggers a 100% solid full-frame blackout.
4. **Forensic Immutability & Dual-Control Separation:**
   - Pristine raw video frames are immutable, encrypted via AES-256-GCM, signed via Ed25519, and sealed in the vault.
   - Privacy-masked derivatives and forensic enhancements are cryptographically linked to originals via persistent `privacy_manifests` and `enhancement_manifests` tables in SQLite.
   - Unmasked evidence export requires on-device dual-control quorum authentication.
5. **Honest Capability Reporting:**
   - Subsystem capabilities are strictly categorized as: `IMPLEMENTED`, `UNIT_TESTED`, `INTEGRATION_TESTED`, `SIMULATED`, `PHYSICAL_HARDWARE_TESTED`, or `PRODUCTION_VALIDATED`. Marketing exaggerations are strictly prohibited.

---

## 4. Ten-Stage Phase 3 Implementation Roadmap

```
+─────────────────────────────────────────────────────────────────────────────────+
|                           PHASE 3 ROADMAP (STAGES 1 - 10)                       |
+─────────────────────────────────────────────────────────────────────────────────+
  Stage 0: Entry Audit, Working Tree Verification & Risk Register [COMPLETED]
     │
     ▼
  Stage 1: CAMserv AI Appliance Architecture & Hardware Abstraction
  (Profiles A/B/C, Thermal/Power Modeling, HardwareCapabilityManager)
     │
     ▼
  Stage 2: CAMserv Dedicated Linux Deployment Environment
  (Appliance OS Specification, Systemd Units, Watchdog, Isolated Image Design)
     │
     ▼
  Stage 3: CAMserv Central & Device Registry
  (Device Enrollment, Cryptographic Identity, Health Telemetry, Multi-Site Registry)
     │
     ▼
  Stage 4: Secure Distributed Communication
  (Mutual TLS, Offline Buffering, Data Minimization, Cryptographic Command Dispatch)
     │
     ▼
  Stage 5: Enterprise Security, Identity & Multi-Tenancy
  (Multi-Tenant Isolation, RBAC Matrix, Server-Side Authorization, Audit Sealing)
     │
     ▼
  Stage 6: Storage & Evidence Infrastructure
  (Tiered Storage, Retention Purging, Database Migrations, Controlled Export)
     │
     ▼
  Stage 7: Device & Platform Lifecycle Management
  (Signed OTA Updates, Ed25519 Verification, Atomic Rollback, Staged Channels)
     │
     ▼
  Stage 8: Professional Operator Experience
  (14 Responsive Screens, Telemetry HUD, Human-in-the-Loop Review Workflow)
     │
     ▼
  Stage 9: Observability & Reliability Engineering
  (OpenTelemetry / Prometheus Metrics, Fault-Injection Chaos, 72h Soak Test Harness)
     │
     ▼
  Stage 10: Commercial Product Engineering & Packaging
  (Community / Professional / Enterprise Editions, SBOM Generation, License Audit)
```

---

## 5. Detailed Stage Specifications

### Stage 1: CAMserv AI Appliance Architecture & Hardware Abstraction
* **Objective:** Design the dedicated turnkey hardware platform across three standardized profiles and engineer a universal hardware abstraction interface (`HardwareCapabilityManager`).
* **Hardware Profiles:**
  - **Profile A (CAMserv Edge):** 4-core ARM64 / x86_64, 8GB RAM, integrated NPU/GPU or CPU inference, 256GB NVMe, fanless industrial enclosure ($15\text{W}$ TDP). Target: 1-4 streams.
  - **Profile B (CAMserv Professional):** 8-core x86_64 (e.g. Intel Core i7 / AMD Ryzen 7), 32GB DDR5, discrete GPU (RTX 4060 or Intel Arc A770), 2TB NVMe + 8TB SATA surveillance HDD ($65\text{W}-120\text{W}$ TDP). Target: 8-16 streams.
  - **Profile C (CAMserv Enterprise):** 16-32 core AMD EPYC / Intel Xeon, 64-128GB ECC RAM, dual NVIDIA RTX 4090 / L40S, 4TB NVMe OS/Vault + 32TB U.2 NVMe RAID ($350\text{W}-600\text{W}$ TDP). Target: 32-64 streams.
* **Key Software Deliverables:**
  - `src/camserv/platform/appliance.py`: Hardware discovery, profile assignment, dynamic workload throttle governor, thermal safety watchdogs.
  - `src/camserv/inference/supervisor.py`: OS-isolated `InferenceWorkerSupervisor` resolving SEC-05 by isolating ONNX/CUDA inference crashes from the core application.
* **Acceptance Gate:** Hardware capability benchmarks run reliably across CPU, DirectML, CUDA, and OpenVINO without hardcoded assumptions.

---

### Stage 2: CAMserv Dedicated Linux Deployment Environment
* **Objective:** Define a hardened, minimal, reproducible deployment environment for dedicated CAMserv appliances without interfering with developer workstations.
* **Base OS Foundation:** Debian 12 (Bookworm) Stable / Ubuntu 24.04 LTS Minimal.
* **Key Components:**
  - Minimal read-only root filesystem overlay (`overlayfs`) with persistent `/data` and `/var/log` partitions.
  - Independent systemd unit service tree:
    - `camserv-core.service`: Main orchestrator and API server.
    - `camserv-ingestion.service`: Isolated video decoding supervisor.
    - `camserv-inference.service`: Isolated neural inference worker.
    - `camserv-agent.service`: Secure communication link to CAMserv Central.
  - Software watchdog (`systemd-watchdog`) with automated recovery on freeze ($< 15\text{s}$).
  - Isolated build recipe (Packer / Docker rootfs generator) ensuring zero interaction with host OS.
* **Acceptance Gate:** Complete service supervision definitions, boot scripts, and recovery procedures documented and syntax-validated.

---

### Stage 3: CAMserv Central & Device Registry
* **Objective:** Build the centralized fleet management foundation to securely manage distributed appliances across multiple geographical sites.
* **Key Components:**
  - `DeviceRegistry`: Manages `device_id`, cryptographic public key, site identifier, hardware profile, software release version, and real-time connectivity status.
  - **Cryptographic Device Enrollment:** Cryptographic challenge-response handshake; unknown nodes are untrusted until an authorized operator approves enrollment.
  - **Logical Multi-Site Partitioning:** Strict site boundaries (`Site A`, `Site B`, `HQ`) ensuring site-specific operators cannot observe or modify devices belonging to other locations.
* **Key Software Deliverables:**
  - `src/camserv/central/registry.py`: High-concurrency device registry with SQLite/PostgreSQL abstraction.
  - `src/camserv/central/models.py`: Pydantic dataclasses for device state, health telemetry, and enrollment tokens.
* **Acceptance Gate:** 100% rejection of unauthorized enrollment requests and mathematical isolation of cross-site device records verified by integration tests.

---

### Stage 4: Secure Distributed Communication
* **Objective:** Establish zero-trust, authenticated, low-bandwidth communication between edge appliances and CAMserv Central.
* **Protocol Architecture:**
  - **Transport Layer:** Mutual TLS v1.3 (mTLS) with appliance-specific X.509 client certificates issued during enrollment.
  - **Data Minimization:** No continuous video upload over WAN. Edge appliances transmit **health telemetry, event metadata, and signed cryptographic manifests** exclusively.
  - **Store-and-Forward Message Buffering:** Persistent local SQLite message queue buffer (`offline_buffer.db`) that caches events during network disconnections and seamlessly flushes with replay protection upon reconnection.
* **Acceptance Gate:** Simulated WAN disconnections demonstrate zero loss of security events and zero exposure of raw video over external interfaces.

---

### Stage 5: Enterprise Security, Identity & Multi-Tenancy
* **Objective:** Provide enterprise-grade Role-Based Access Control (RBAC), multi-tenancy isolation, and tamper-sealed audit trails.
* **RBAC Matrix:**
  - `SUPER_ADMIN`: Global fleet management, license management, tenant provisioning.
  - `SITE_ADMIN`: Local camera configuration, user management for assigned site.
  - `SECURITY_OPERATOR`: Live monitoring (privacy-masked), event triage, human-in-the-loop review.
  - `FORENSIC_INVESTIGATOR`: Derivative evidence review, judicial export with manifest validation.
  - `AUDITOR`: Read-only access to cryptographic audit logs and compliance scorecards.
* **Security Controls:**
  - Server-side authorization tokens (JWT signed with Ed25519).
  - Cross-tenant access attempts immediately trigger security alert and log entry.
  - Audit trails sealed with Merkle trees and isolated from standard debug logging.
* **Acceptance Gate:** Dedicated security unit tests verifying that tenant and role boundaries cannot be bypassed via forged API requests.

---

### Stage 6: Storage & Evidence Infrastructure
* **Objective:** Implement an enterprise storage management architecture supporting operational video retention, forensic vaulting, and transaction-safe database migrations.
* **Storage Tiers:**
  1. **Operational Tier (Fast NVMe):** 15-second continuous RAM pre-roll buffer + rolling 72-hour high-efficiency recording.
  2. **Forensic Vault Tier (Surveillance Storage):** AES-256-GCM encrypted incident chunks, Ed25519 signatures, and SQLite manifest indices.
  3. **Archival / Export Tier:** Removable encrypted media or external S3/NFS targets with court-ready verification packages.
* **Database Migration Engine:**
  - Lightweight, zero-dependency transactional migration manager (`MigrationManager`) executing forward and backward schema versions with automatic backup before execution.
* **Acceptance Gate:** Simulated unexpected system power cutoff causes zero data corruption or unhandled database lockups.

---

### Stage 7: Device & Platform Lifecycle Management
* **Objective:** Implement a secure, signed over-the-air (OTA) software update and recovery architecture.
* **Key Invariants:**
  - **Ed25519 Cryptographic Signatures:** Update payloads must be cryptographically signed by the official CAMserv Release Authority. Unsigned or corrupted archives are rejected before extraction.
  - **A/B Dual Partition / Rollback Architecture:** Updates are installed into an inactive partition/container slot. If health checks fail during post-update boot, the system automatically reverts to the previous working slot.
  - **Maintenance Window Controls:** Updates can be scheduled during low-activity windows with explicit operator approval.
* **Acceptance Gate:** Signature verification tests reject tampered update bundles and verify atomic rollback.

---

### Stage 8: Professional Operator Experience & UI Design System
* **Objective:** Deliver a cohesive, high-performance web and desktop operations console matching the 14 visual screens.
* **Screen Portfolio:**
  1. Security Operations Dashboard
  2. Live Camera Wall (multi-stream matrix with fail-closed mosaic overlays)
  3. Camera Management
  4. Device & Appliance Management
  5. AI Intelligence Monitor (kinematic pose telemetry and threat scoring)
  6. Event Investigation (timeline scrubber, reasoning trace, observation tokens)
  7. Evidence Explorer (dual-hash manifest verification, side-by-side comparison)
  8. Privacy Configuration (fail-closed toggles, zone masking, role policies)
  9. Storage Management (capacity breakdown, retention schedule, disk health)
  10. Hardware Diagnostics (CPU/GPU temperature, VRAM, provider hierarchy)
  11. System Health (service supervisor statuses, memory consumption)
  12. User & Permission Management (RBAC assignments, session controls)
  13. Central Multi-Site Management (geographic fleet topology, tenant switcher)
  14. Software Update Management (release channel selector, staged rollout)
* **Acceptance Gate:** Web application serves clean, responsive HTML/CSS/JS with zero external CDN dependencies and sub-50ms UI response times.

---

### Stage 9: Observability & Reliability Engineering
* **Objective:** Provide deep diagnostic instrumentation and validate platform endurance under stress.
* **Telemetry Stack:**
  - Prometheus `/metrics` endpoint exposing: stream ingestion FPS, decode latency, inference duration percentiles ($P_{50}, P_{95}, P_{99}$), VRAM usage, dropped frames, active tracks, and privacy blackout counts.
  - OpenTelemetry structured trace spans for frame-to-alert latencies.
* **Reliability & Chaos Harness:**
  - Automated test harnesses simulating: camera network packet loss, RTSP server crashes, inference provider failure, database disk full ($> 95\%$), and thermal throttling.
  - 72-Hour continuous multi-stream soak testing script measuring Resident Set Size (RSS) memory drift and ring buffer stability.
* **Acceptance Gate:** Sustained soak harness demonstrates zero memory leaks ($< 2\%$ variance over 100,000 processed frames).

---

### Stage 10: Commercial Product Engineering & Packaging
* **Objective:** Structure CAMserv for commercial distribution, resolve licensing boundaries, and generate deployment documentation.
* **Commercial Product Tiers:**
  - **CAMserv Community:** Open-source core, up to 4 cameras, single-node, Apache-2.0 model weights, community support.
  - **CAMserv Professional:** Turnkey appliance license, up to 16 cameras, local operator HUD, hardware acceleration, commercial SLA.
  - **CAMserv Enterprise:** Multi-node clustering, CAMserv Central fleet management, unlimited cameras, SSO/RBAC, 24/7 mission-critical support.
* **Software Supply Chain & SBOM:**
  - Automated CycloneDX / SPDX Software Bill of Materials generation.
  - Full licensing register confirming zero copyleft conflicts under closed-source appliance distribution.
* **Acceptance Gate:** Complete product documentation, installation manuals, and licensing certificates prepared and validated.

---

## 6. Stop Conditions & Transition Rules

1. **Stop Condition 1 (Regression):** If any Phase 1 or Phase 2 test fails, the active stage must stop immediately until the regression is diagnosed and remediated.
2. **Stop Condition 2 (Privacy Violation):** If any code change permits unmasked raw video to reach non-vault egress, the stage is halted.
3. **Stop Condition 3 (Evidence Mutation):** If original raw video chunks or SHA-256 digests are overwritten or modified, implementation halts.
4. **Stop Condition 4 (Host Environment Safety):** Any command attempting to modify the developer's personal host bootloader, EFI partition, or physical firmware is strictly prohibited.

---

## 7. Stage 0 Completion & Sign-Off

Stage 0 (Entry Audit, Risk Register, and Architecture Proposal) is formally completed and documented. The engineering baseline is stable (192 passing tests). Approval is granted to proceed to **Stage 1: CAMserv AI Appliance Architecture & Hardware Abstraction**.
