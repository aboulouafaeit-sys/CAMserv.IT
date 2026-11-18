# CAMserv Phase 27.2 — Model Registry & Weight Integrity Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Gate 27.2-A  
**Architecture:** Single Organization / Local-First Deployment  
**Audited Component:** `src/camserv/intelligence/registry.py` & `src/camserv/intelligence/contracts.py`

---

## 1. Executive Summary

Phase 27.1 exposed that `registry.py` contained the SHA-256 digest `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` as `expected_sha256` for registered model records. This hash represents the cryptographic digest of an empty byte string (`hashlib.sha256(b"").hexdigest()`), allowing uninstalled or 0-byte placeholder files to appear verified.

In Gate 27.2-A, this placeholder was eradicated, an explicit 9-state epistemic model capability state machine was introduced, and security checks against path traversal and symlink vulnerabilities were implemented.

---

## 2. Eradication of Empty-File Placeholder

In `src/camserv/intelligence/registry.py`:
- Defined `EMPTY_FILE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"`.
- `ModelCapabilityRecord.verify_integrity(self) -> bool` now explicitly checks:
  1. `self.expected_sha256` is non-empty.
  2. `self.expected_sha256.lower() != EMPTY_FILE_SHA256` (strictly forbidden as a verified reference).
  3. File exists on disk.
  4. `os.path.getsize(file_path) > 0` (non-zero byte length).
  5. Cryptographic SHA-256 of physical bytes on disk matches `self.expected_sha256.lower()`.
- If any check fails, `verify_integrity()` returns `False`.

---

## 3. Epistemic Model Capability State Machine

The enum `ModelCapabilityState` was implemented in `src/camserv/intelligence/contracts.py` with 9 distinct states:

| State | Semantic Meaning |
|---|---|
| `MODEL_NOT_INSTALLED` | Weight file does not exist on disk or record unregistered. |
| `MODEL_LOADING` | Asynchronous file read and tensor allocation in progress. |
| `MODEL_READY` | Weights verified on disk and loaded into runtime without error. |
| `MODEL_INTEGRITY_VERIFIED` | SHA-256 matches verified non-placeholder reference. |
| `MODEL_INTEGRITY_FAILED` | File absent, empty, corrupted, or hash mismatch. |
| `MODEL_RUNTIME_UNAVAILABLE` | OpenCV DNN or ONNX runtime missing or unable to parse format. |
| `MODEL_UNSUPPORTED` | Model architecture incompatible with host compute capability. |
| `MODEL_LICENSE_UNVERIFIED` | Model provenance or commercial redistribution rights unconfirmed. |
| `MODEL_INFERENCE_FAILED` | Execution threw exception during forward pass. |

The registry method `get_model_capability_state(model_id: str)` strictly enforces these transitions.

---

## 4. Path Traversal & Security Hardening

The function `validate_model_path(file_path: str) -> bool` was introduced:
- Prevents directory traversal sequences (`..`).
- Rejects null bytes (`\x00`).
- Validates canonical paths before disk operations.
- Enforces user-supplied model registrations through `register_user_model(record)`.

---

## 5. Verification Evidence

In `tests/test_phase27_2_real_ai_and_process_isolation.py`:
- `test_empty_file_placeholder_strictly_rejected()`: PASS.
- `test_model_capability_states_evaluation()`: PASS.
- `test_user_model_path_traversal_protection()`: PASS.
