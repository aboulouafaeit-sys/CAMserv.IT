# CAMserv Phase 27.2 — Model Licensing & Supply Chain Security Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Supply Chain & Licensing Review  
**Architecture:** Single Organization / Local-First Deployment  

---

## 1. Executive Summary

Phase 27.2 audited the model supply chain, legal licensing constraints, commercial redistribution rights, and runtime vulnerability exposure across all registered AI capabilities.

In accordance with strict operational directives:
1. No unverified third-party neural weights or proprietary binary blobs are bundled into CAMserv without clear redistribution clearance.
2. Default model profiles declare explicit open-source licenses (Apache-2.0, MIT, BSD-3-Clause).
3. Local deployment installations utilize user-provided model paths validated against cryptographic checksums.

---

## 2. Model License Inventory

| Model Identifier | Architecture | Declared License | Commercial Rights | Input Dimensions | Memory Footprint | Minimum Tier |
|---|---|---|---|---|---|---|
| `camserv_det_cpu_v1` | `opencv_dnn_ssd` | Apache-2.0 | Permitted | $416\times416$ | 45.0 MB | Tier A (CPU Low) |
| `camserv_anpr_ocr_v1` | `crnn_ctc_ocr` | MIT | Permitted | $320\times96$ | 25.0 MB | Tier B (iGPU/NPU) |

### Commercial Use Analysis
- **Apache-2.0:** Grants permissive rights for commercial distribution, modification, and private use, requiring standard copyright and license notices.
- **MIT:** Fully permissive, allowing commercial utilization without patent retaliation risk.
- **Prohibited Licenses:** Non-commercial (CC-BY-NC) and restrictive reciprocal licenses (GPLv3) are barred from the core CAMserv appliance image to ensure enterprise compliance.

---

## 3. Supply Chain Security Controls

1. **Deterministic Checksum Verification:**
   - Every model profile enforces `expected_sha256`.
   - The empty-file placeholder digest (`e3b0c442...`) is strictly prohibited.
2. **Path Traversal & Reparse Point Protection:**
   - `validate_model_path()` rejects relative traversal sequences (`..`), null characters (`\x00`), and verifies path boundaries.
3. **Execution Sandbox & Privilege Separation:**
   - Inference execution is delegated to isolated OS child processes via `ProcessIsolatedInferenceSupervisor`.
   - Child processes run with least privilege and have no access to camera credentials, database encryption keys, or forensic audit logs.
4. **Vulnerability Assessment:**
   - Model files are loaded via OpenCV's C++ DNN engine (`cv2.dnn.readNet`), avoiding pickle-based deserialization hazards (`torch.load` arbitrary code execution risks).
