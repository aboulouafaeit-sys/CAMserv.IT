# CAMserv Software Supply Chain & Release Security Plan
**Document ID:** SEC-SUPPLY-2026-001  
**Author:** Principal DevSecOps Architect & Release Security Lead  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Standards:** NIST SP 800-218 (SSDF), SLSA Level 3, SPDX v2.3, CycloneDX v1.5, Cosign / Sigstore

---

## 1. Supply Chain Defense Principles

Critical surveillance platforms must be safeguarded against malicious upstream dependency compromises, compromised build pipelines, and untracked third-party vulnerabilities.

CAMserv enforces four core supply chain requirements:
1. **Deterministic Hermetic Builds:** Zero unpinned dynamic dependencies; all runtime packages are locked via cryptographic SHA-256 hashes in `requirements.lock`.
2. **Automated Software Bill of Materials (SBOM):** Machine-readable CycloneDX and SPDX SBOM manifests generated for every build.
3. **Continuous CVE Vulnerability Gating:** Automated pipeline gates blocking releases with Critical or High Common Vulnerabilities and Exposures (CVEs).
4. **Cryptographic Artifact Signing:** Container images, wheels, and model weights are signed using **Cosign / Sigstore** with public transparency logs.

---

## 2. Dependency Pinning & Vulnerability Scanning Workflow

```
+---------------------------------------------------------------------------------+
|                       CAMSERV SECURE BUILD PIPELINE                             |
|                                                                                 |
|   +-----------------------+     +-----------------------+     +---------------+ |
|   | pyproject.toml        | --> | pip-compile --generate| --> | Pipfile.lock/ | |
|   | Core & Extra Deps     |     | --hashes              |     | requirements  | |
|   +-----------------------+     +-----------------------+     +-------+-------+ |
|                                                                       |         |
|   +-----------------------+     +-----------------------+             v         |
|   | Trivy & Grype CVE Scan| <-- | Container Image Build | <-----------+         |
|   +-----------+-----------+     +-----------------------+                       |
|               |                                                                 |
|               v (Zero Critical/High CVEs)                                       |
|   +-----------------------+     +-----------------------+                       |
|   | Cosign Release Signing| --> | OCI Artifact Registry |                       |
|   +-----------------------+     +-----------------------+                       |
+---------------------------------------------------------------------------------+
```

### 2.1 Dependency Audit & Lockdown Strategy
* **Direct Dependencies:** `fastapi`, `pydantic`, `cryptography`, `structlog`, `opencv-python-headless`, `numpy`, `scipy`.
* **Lockfile Enforcement:** In production, installation commands enforce strict hash checking:
  ```bash
  pip install --no-deps --require-hashes -r requirements.lock
  ```
* **Daily Automated Vulnerability Scans:** `pip-audit` runs in continuous integration to catch newly disclosed zero-day vulnerabilities in transitive dependencies.

---

## 3. Cryptographic Release Signing & Model Verification

* **Model Weight Verification:** Neural network weights (`models/yolov8n-seg.onnx`) carry SHA-256 integrity checksums verified at application startup before loading into GPU VRAM:
  ```python
  EXPECTED_MODEL_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  ```
* **Release Artifact Signing:** Every published Docker container image (`ghcr.io/aboulouafaeit-sys/camserv`) is signed with Cosign:
  ```bash
  cosign sign --key cosign.key ghcr.io/aboulouafaeit-sys/camserv:2.5.0
  ```
