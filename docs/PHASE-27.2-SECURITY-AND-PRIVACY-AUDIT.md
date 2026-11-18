# CAMserv Phase 27.2 — Security & Privacy Audit Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Security & Privacy Assurance  
**Architecture:** Single Organization / Local-First Deployment  

---

## 1. Executive Summary

Phase 27.2 audited security trust boundaries, model deserialization safety, worker process isolation, ANPR privacy governance, and audit logging.

The audit verified that AI worker processes run with least privilege, cannot access administrative credentials, cannot mutate raw video recordings, and that all ANPR activity is governed by immutable audit logging and human review workflows.

---

## 2. Security Trust Boundary Matrix

| Asset / Subsystem | Main CAMserv Process | AI Worker Child Process | Threat Mitigation |
|---|---|---|---|
| Camera RTSP Credentials | Read / Write | **No Access** | Credentials never passed over IPC |
| Recording Video Vault | Master Write Access | **No Access** | Worker cannot mutate raw video |
| Evidence WAL Database | Master Access | **No Access** | Worker returns ephemeral result dictionaries |
| Model Weights | File System Read | File System Read (Path-validated) | Path traversal check via `validate_model_path()` |
| Admin / Token Store | Master Access | **No Access** | Worker runs without session tokens |
| IPC Channels | Queue Master | Queue Consumer | Typed, bounded, serialized dataclasses |

---

## 3. Vulnerability Surface Assessment

1. **Arbitrary Code Execution via Deserialization:**
   - Mitigated: PyTorch pickle deserialization (`torch.load`) is barred. Models are parsed via OpenCV C++ ONNX/SSD parsers.
2. **Path Traversal Attacks:**
   - Mitigated: `validate_model_path()` rejects `..`, null bytes, and absolute escapes outside registered roots.
3. **IPC Resource Exhaustion (OOM DOS):**
   - Mitigated: `task_queue` and `result_queue` enforce bounded depth (`maxsize = 8`). Large frame buffers are isolated.
4. **Stale Result Leaks / Race Conditions:**
   - Mitigated: Generation epoch counters and unique task lease UUIDs prevent terminated workers from injecting delayed predictions.

---

## 4. Privacy & Regulatory Compliance (GDPR / AI Act)

- **Biometric & Face Recognition:** Barred from CAMserv. No facial recognition, emotion analysis, or biometric identification is supported.
- **ANPR Governance:** Disabled by default. Activation requires documented legal justification. All queries logged to audit trail.
- **Anonymous Tracking:** Tracks are identified by ephemeral integer IDs scoped to camera session (`track_id`). Cross-camera tracking and persistent person identity databases are strictly omitted.
- **Human-in-the-Loop:** All ANPR and critical intelligence events default to `PENDING_REVIEW` or `UNREVIEWED`. Consequential decisions require operator verification.

---

## 5. Verification Evidence

In `tests/test_phase27_2_real_ai_and_process_isolation.py`:
- `test_user_model_path_traversal_protection()`: PASS.
- `test_anpr_optical_gating_blur_and_glare()`: PASS.
- In `tests/test_phase27_anpr_pipeline.py`:
  - `test_anpr_disabled_by_default_and_unauthorized_rejection()`: PASS.
