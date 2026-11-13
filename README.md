<p align="center">
  <img src="src/camserv/web/assets/logo-primary-dark.svg" alt="CAMserv Logo" width="460">
</p>

<p align="center">
  <strong>Advanced, Modular, Privacy-Preserving Security Intelligence Platform</strong><br>
  Real-time video analytics, anonymous multi-object tracking, on-device AI inference, and tamper-evident digital forensics.
</p>

<p align="center">
  <a href="#test-results"><img src="https://img.shields.io/badge/Tests-115%20Passing-10B981?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-06B6D4?style=for-the-badge&logo=python&logoColor=white" alt="Python"></a>
  <a href="#hardware-compatibility"><img src="https://img.shields.io/badge/CUDA-13.5%20%2F%20RTX%203060%2B-76B900?style=for-the-badge&logo=nvidia&logoColor=white" alt="CUDA"></a>
  <a href="docs/PRIVACY.md"><img src="https://img.shields.io/badge/GDPR%20%26%20EU%20AI%20Act-Conformity-6366F1?style=for-the-badge&logo=shield&logoColor=white" alt="Compliance"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-F59E0B?style=for-the-badge" alt="License"></a>
</p>

---

## 1. Executive Summary

**CAMserv** is an industrial-grade security intelligence platform engineered for critical infrastructure, corporate facilities, and high-assurance environments. It combines high-throughput video ingestion, on-device neural acceleration, anonymous multi-object tracking, and explainable temporal reasoning into a coherent, privacy-first product.

### Core Architectural Pillars
* **Epistemic Transparency:** Every algorithmic detection is explicitly flagged (`is_prediction: bool = True`) with bounded confidence $p \in [0.0, 1.0]$. Inferences are never treated as facts.
* **Strict Non-Biometric Anonymity:** Multi-object tracking (ByteTrack and BoT-SORT) enforces transient anonymous integer IDs. No facial recognition, biometric templates, or persistent identities are ever constructed or stored.
* **Mandatory Human-in-the-Loop (HITL):** High-severity events (`severity >= HIGH`) automatically require authorized operator review and sign-off before consequential physical or automated actions are dispatched.
* **Digital Forensics & Non-Repudiation:** Evidence bundles are cryptographically sealed with AES-256-GCM encryption, continuous SHA-256 hash chaining, and asymmetric Ed25519 digital signatures.
* **On-Device Execution & Graceful Fallback:** Native execution on NVIDIA TensorRT / CUDA with automated fallback to ONNX Runtime CPU.

---

## 2. The 12 Official CAMserv Product Screens

CAMserv features an embedded, high-performance web console served directly at `http://localhost:8000/`:

| Screen # | Operational View | Purpose & Technical Scope |
| :---: | :--- | :--- |
| **01** | **Executive Overview** | Real-time KPI summaries, active camera statuses, pending review queue, and 24h event volume. |
| **02** | **Live Monitoring** | Quad/multi-view video wall with real-time bounding box and dynamic privacy-mask overlays. |
| **03** | **Camera Management** | RTSP/ONVIF camera inventory with interactive polygon geometric privacy mask editor. |
| **04** | **Intelligent Event Center** | Filterable security event stream with multi-frame observation graphs and operator sign-off workflow. |
| **05** | **Anonymous Tracking** | Real-time spatial tracking visualization, kinematic velocities, MOTA/MOTP accuracy metrics. |
| **06** | **Incident Investigation** | Multi-camera synchronized temporal timeline reconstruction and cross-camera correlation. |
| **07** | **Evidence Vault** | Tamper-evident evidence storage with one-click cryptographic hash chain auditing. |
| **08** | **Analytics & Reports** | Crowd density trend analysis, vehicle classification breakdowns, and automated GDPR purge logs. |
| **09** | **Device & NVR Integration** | Subnet ONVIF WS-Discovery scanner and NVR stream stability benchmark utility. |
| **10** | **Security & Access Control** | User RBAC management (`ADMIN`, `OPERATOR`, `VIEWER`, `AUDITOR`) and immutable audit log viewer. |
| **11** | **System Health** | Host CPU/RAM/GPU diagnostics, DDSketch P50/P95/P99 latency histograms, queue fill ratios. |
| **12** | **Deployment & Config** | Live platform configuration tuning with schema validation and automated backup triggers. |

---

## 3. High-Level System Architecture

```mermaid
graph TD
    subgraph INGEST ["1. Video Acquisition & Decoding"]
        CAM1["ONVIF / RTSP Cameras"] --> INGESTION["CameraStream Engine"]
        NVR["Enterprise NVRs (Hikvision/Dahua/Axis)"] --> INGESTION
        INGESTION --> DECODER["FrameDecoder (Resizing, Color, Dedup)"]
    end

    subgraph ENGINE ["2. Core Processing Pipeline"]
        DECODER --> BACKPRESSURE["Bounded Queue (drop_oldest)"]
        BACKPRESSURE --> DETECTOR["ObjectDetector (ONNX GPU/CPU / FP16)"]
        DETECTOR --> PRIVACY["PrivacyFilter (Face & Body Blurring)"]
        PRIVACY --> TRACKER["Anonymous Multi-Object Tracker (ByteTrack / BoT-SORT)"]
        TRACKER --> EVENTS["TemporalEventEngine (State Machines & Kinematics)"]
    end

    subgraph STORAGE ["3. Persistence & Forensics"]
        EVENTS --> SQLITE[("SQLite WAL Store<br/>(Cameras, Events, Users)")]
        EVENTS --> REDIS[("Redis Cache<br/>(Active Tracks & State)")]
        EVENTS --> MILVUS[("Milvus Vector Store<br/>(Non-Biometric Scene Vectors)")]
        EVENTS --> EVIDENCE[("Tamper-Evident Evidence Store<br/>(AES-256-GCM + Ed25519 Signatures)")]
        EVENTS --> AUDIT[("Immutable Audit Trail<br/>(SHA-256 Hash Chain)")]
    end

    subgraph PRESENTATION ["4. User Experience & Interfaces"]
        SQLITE --> FASTAPI["FastAPI Production API"]
        REDIS --> FASTAPI
        EVIDENCE --> FASTAPI
        AUDIT --> FASTAPI
        FASTAPI --> CONSOLE["CAMserv Web Console (12 Screens)"]
        FASTAPI --> WS["Real-time WebSocket Feeds"]
        FASTAPI --> CLI["Unified CLI Engine (camserv)"]
    end
```

---

## 4. Quickstart & Installation

### 4.1 Prerequisites
* Python 3.11, 3.12, 3.13, or 3.14
* Git
* (Recommended) NVIDIA GPU with CUDA 12.x or 13.x

### 4.2 Installation
```bash
# Clone the repository
git clone git@github.com:aboulouafaeit-sys/CAMserv.IT.git
cd CAMserv.IT

# Install in editable mode with all dependencies
pip install -e ".[all]"
```

### 4.3 Command-Line Interface (CLI)
CAMserv includes a unified CLI for runtime, forensics, and diagnostics:

```bash
# 1. Run Host Hardware Diagnostic Probe
python -m camserv.main detect-hw

# 2. Verify Cryptographic Audit Log Integrity
python -m camserv.main audit-verify

# 3. Scan Local Subnet for ONVIF Compliant Cameras
python -m camserv.main nvr-scan

# 4. Test Specific RTSP Endpoint Compatibility
python -m camserv.main nvr-scan --url rtsp://admin:pass@192.168.1.100:554/live/ch0

# 5. Offline Independent Forensic Verification of an Evidence Package
python -m camserv.main verify-evidence evidence_archive.zip --public-key server_pubkey.pem

# 6. Launch the CAMserv Server & Web Console
python -m camserv.main serve --host 127.0.0.1 --port 8000
```

Once running, navigate to `http://localhost:8000/` in any modern web browser to access the **CAMserv Enterprise Web Console**.

---

## 5. Verification & Test Suite

The platform includes 115 comprehensive automated test cases across 17 test modules:

```bash
# Execute the full automated test suite
python -m pytest tests/ -v
```

```text
tests/scenarios/test_integration.py .....                                [  4%]
tests/test_adversarial.py .............                                  [ 15%]
tests/test_api.py .........                                              [ 23%]
tests/test_config.py ......                                              [ 28%]
tests/test_events.py ...........                                         [ 38%]
tests/test_forensics.py ....                                             [ 41%]
tests/test_inference.py ..........                                       [ 50%]
tests/test_main_cli.py ....                                              [ 53%]
tests/test_onvif.py ..                                                   [ 55%]
tests/test_pipeline.py ........                                          [ 62%]
tests/test_platform_hardware.py ..                                       [ 64%]
tests/test_security.py .............                                     [ 75%]
tests/test_sqlite_store.py ...                                           [ 78%]
tests/test_storage.py ........                                           [ 85%]
tests/test_temporal_events.py ..                                         [ 86%]
tests/test_tracking.py ............                                      [ 97%]
tests/test_web_console.py ...                                            [100%]
======================== 115 passed in 12.58s =========================
```

---

## 6. Architecture & Governance Records

For in-depth architectural and legal documentation:
* [ARCHITECTURE.md](docs/ARCHITECTURE.md) — Subsystem interfaces, performance budgets, and queue mechanics.
* [SECURITY.md](docs/SECURITY.md) — STRIDE threat modeling, key management, and cryptographic protocols.
* [PRIVACY.md](docs/PRIVACY.md) — GDPR compliance, EU AI Act conformity assessment, and DPIA templates.
* [API.md](docs/API.md) — Complete REST and WebSocket API specification.
* [DEPLOYMENT.md](docs/DEPLOYMENT.md) — Production Docker Compose, Nginx TLS 1.3, and clustering guide.
* [BRAND_GUIDELINES.md](docs/brand/BRAND_GUIDELINES.md) — Visual identity system, typography, and vector assets.
* [Architecture Decision Records (ADRs)](docs/adr/) — Formal record of architectural decisions.

---

## 7. License

CAMserv is distributed under the [MIT License](LICENSE).
