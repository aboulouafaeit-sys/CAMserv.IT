# CAMserv — Phase 3 Product Edition & Commercial Strategy

**Document Status:** Production Engineering Architecture Reference  
**Product Baseline:** CAMserv Phase 3 Milestone 10  
**Target Audience:** Enterprise Solutions Architects, Legal & Compliance Counsel, Commercial OEM Partners, Executive Engineering Leadership  

---

## 1. Executive Summary

As CAMserv matures from an edge video analytics engine into a commercial-grade enterprise intelligence ecosystem, a clear packaging, licensing, and edition strategy is essential. This document articulates the product tiering, architectural capability boundaries, copyleft avoidance safeguards, Software Bill of Materials (SBOM) compliance, and commercial operational model across:

1. **CAMserv Community Edition (OSS / Free Core)**
2. **CAMserv Professional Edition (Turnkey Appliance)**
3. **CAMserv Enterprise Edition (Clustered Multi-Site Fleet)**

---

## 2. Product Editions Capability Matrix

| Architectural Capability | Community Edition | Professional Edition | Enterprise Edition |
| :--- | :---: | :---: | :---: |
| **Target Deployment** | Single workstation / SOHO | Dedicated Turnkey Appliance | Clustered Enterprise Datacenter / Multi-Site |
| **Maximum Stream Capacity** | **Up to 4 Streams** | **Up to 16 Streams** | **Up to 1,024 Streams per Cluster** |
| **Hardware Acceleration** | CPU Only (ONNX CPU) | GPU / NPU (CUDA, TensorRT, OpenVINO, DirectML) | Multi-GPU Clustered Acceleration |
| **Fail-Closed Privacy Masking** | **MANDATORY (Unconditional)** | **MANDATORY (Unconditional)** | **MANDATORY (Unconditional)** |
| **Storage Architecture** | Single Local Directory | Tiered Storage (RAM / NVMe / Cold) | Tiered Storage + Remote Forensic Vault |
| **Retention & Judicial Hold** | Basic Auto-Purge | Automated 48h Retention + Judicial Lock | Multi-Policy Tiered Retention + Quorum Hold |
| **Evidence Export Gate** | Local Export (SHA-256) | Encrypted BagIt Container | Dual-Control Quorum Authorized Export |
| **Security & Multi-Tenancy** | Single User Local | Single Organization Local | Strict Multi-Tenant Isolation (Server-Side) |
| **RBAC Roles** | Administrator Only | Admin, Operator, Auditor | 6-Tier Enterprise RBAC + Quorum Engine |
| **Central Fleet Management** | Not Supported | Supported as Managed Node | Central Master Controller + Fleet Mesh |
| **WAN Data Minimization** | N/A | Strictly Enforced (Zero Raw Video) | Strictly Enforced (Metadata/Embeddings Only) |
| **Update Infrastructure** | Manual Git / Wheel Pull | Signed OTA Updates (A/B Slots) | Staged Multi-Ring Fleet Updates (A/B Slots) |
| **Licensing Model** | Open Source (MIT / Apache-2.0) | Commercial Turnkey OEM License | Enterprise Annual Subscription / Multi-Site |

---

## 3. Universal Architectural Invariant: Non-Negotiable Privacy

A core foundational principle of CAMserv is that **privacy and civil liberties protection is never a monetized luxury feature**.

```
+-----------------------------------------------------------------------------------+
|                           UNIVERSAL PRIVACY INVARIANT                             |
|                                                                                   |
|   Regardless of license tier (Community, Professional, or Enterprise):            |
|                                                                                   |
|   1. Fail-Closed Privacy Pipeline is PERMANENTLY ACTIVE and CANNOT BE DISABLED.  |
|   2. Any inference, detector, or masking failure immediately triggers             |
|      Full-Frame Blackout.                                                         |
|   3. Raw video streams are NEVER transmitted over WAN or displayed to regular     |
|      operators without formal Dual-Control Quorum authorization.                  |
|   4. Privacy masking applies identically across all resolutions and framerates.  |
+-----------------------------------------------------------------------------------+
```

Neither Community nor Enterprise configurations permit setting `fail_closed_privacy_enforced = False`. Any attempt to bypass or suppress privacy filtering results in an immediate pipeline termination.

---

## 4. Open-Source vs. Commercial Intellectual Property & Copyleft Strategy

Commercial deployment of AI video systems faces significant intellectual property and legal hazards when open-source dependencies carry viral copyleft licenses (e.g., GNU GPL-3.0 or AGPL-3.0). CAMserv implements a strict dual-strategy framework to preserve commercial integrity:

### 4.1 Strategy A: Pure Permissive Distribution (Default Production Baseline)

- **Runtime License:** All distributed CAMserv proprietary and open core components are licensed under the MIT License or Apache License 2.0.
- **Dependency Vetting:** All runtime dependencies in `pyproject.toml` (such as `pydantic`, `cryptography`, `structlog`, `aiohttp`, `uvicorn`, `fastapi`, `numpy`, `onnxruntime`) are vetted for permissive licensing (MIT, Apache-2.0, BSD-3-Clause, PSF).
- **AI Models & Weights:** Model weights distributed with appliances utilize permissively licensed architectures (e.g., ONNX exports under Apache-2.0 or MIT-licensed detectors such as ByteTrack and MobileNetV4).
- **OEM Freedom:** Appliance manufacturers and enterprise customers can embed and bundle CAMserv binaries without being legally compelled to disclose proprietary derivative code.

### 4.2 Strategy B: Isolated IPC Boundary for Optional Copyleft Components

In deployments where an operator or enterprise explicitly requests an AGPL-licensed model or tool (such as upstream Ultralytics packages):
- The copyleft component is **strictly isolated** into an external process or microservice container communicating via gRPC or Unix domain sockets with a defined protobuf API.
- The core CAMserv platform maintains clean separation across this network boundary, ensuring no dynamic or static linking occurs, adhering strictly to FSF and copyright jurisprudence regarding IPC-separated programs.

---

## 5. Software Bill of Materials (SBOM) & Supply Chain Integrity

CAMserv embeds an automated SBOM generation pipeline compliant with Executive Order 14028 and European Union Cyber Resilience Act (CRA) standards.

### 5.1 Automated SBOM Generation Tool

The platform provides `scripts/generate_sbom.py`, which analyzes:
- Direct and transitive Python dependencies.
- Model artifact provenance, suppliers, and weight licensing terms.
- Cryptographic signatures and package hashes.
- Automated copyleft risk detection.

```bash
# Generate enterprise CycloneDX 1.5 JSON SBOM
python scripts/generate_sbom.py --format cyclonedx --output deploy/sbom/camserv-sbom.json --strict
```

### 5.2 CycloneDX Component Categorization

Each component in the generated SBOM is categorized according to its function:
- `application`: Core CAMserv platform engine.
- `library`: Permissively licensed system and cryptographic packages (`cryptography`, `pyjwt`, `onnxruntime`).
- `machine-learning-model`: Explicitly audited ONNX model weights and tracking algorithms with supplier provenance and copyleft assessment tags.

---

## 6. Commercial Delivery Packaging & Appliance Lifecycle

### 6.1 CAMserv Community
- **Distribution:** PyPI wheels, GitHub source releases, and single-container Docker images.
- **Audience:** Developers, security researchers, academic labs, and small home offices.
- **Support:** Community forums and GitHub discussions.

### 6.2 CAMserv Professional (Turnkey AI Appliance)
- **Distribution:** Pre-installed on certified hardware profiles (Profile A / Profile B), delivered as an immutable raw disk image (`camserv-appliance-os.raw.zst`).
- **Provisioning:** Zero-touch initial boot wizard, automated storage pool formatting, hardware watchdog activation, and local HTTPS certificate generation.
- **Updates:** Cryptographically signed OTA delta packages delivered via secure A/B slot partition updates.
- **Support:** 8x5 Business Hours support with 24-hour hardware replacement warranty.

### 6.3 CAMserv Enterprise (Clustered Multi-Site)
- **Distribution:** Multi-node orchestration manifests (Kubernetes / Podman systemd fleets), appliance fleet controller, and central management gateway.
- **Features:** Multi-site device enrollment, automated certificate authority (mTLS), centralized telemetry aggregation, hierarchical tenant isolation, and dual-control forensic review.
- **Support:** 24x7 Mission-Critical SLA, dedicated technical account manager, continuous security vulnerability patching, and certified compliance audit assistance.

---

## 7. Licensing Validation Engine Architecture

Feature gating and camera stream quotas are enforced in the core engine via `camserv.config.editions.EditionRegistry`:

```python
# Capacity check during camera stream registration
EditionRegistry.validate_camera_allocation(current_edition, requested_camera_count)

# Enterprise feature validation
EditionRegistry.validate_feature_access(current_edition, "multi_site")
EditionRegistry.validate_feature_access(current_edition, "dual_control_quorum")
```

Any unauthorized feature access or camera quota breach raises an explicit `EditionCapabilityExceededError`, preventing silent misconfiguration or unlicensed cluster expansion while maintaining rock-solid system stability.
