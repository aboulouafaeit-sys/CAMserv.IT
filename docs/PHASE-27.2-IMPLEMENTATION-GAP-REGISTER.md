# CAMserv Phase 27.2 — Implementation Gap Register

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Epistemic Truthfulness & Gap Register  
**Architecture:** Single Organization / Local-First Deployment  

---

## 1. Executive Summary

This register honestly enumerates the implementation status of all Phase 27 and Phase 27.2 capabilities, clearly distinguishing:
- **Verified Real:** Fully implemented with real code, verified against physical artifacts, and validated with tests.
- **Partially Implemented / Gated:** Functional under specific constraints, transparently disclosing limitations.
- **Explicitly Deferred:** Requires physical field hardware, accredited laboratory qualification, or external licensed weights.

---

## 2. Capabilities Status Register

| Subsystem / Capability | Phase 27.1 State | Phase 27.2 State | Current Classification | Epistemic Disclosure |
|---|---|---|---|---|
| **Model Registry** | Empty-file hash accepted | Empty-file hash forbidden, 9 capability states | **Verified Real** | Corrupted or missing weights report `MODEL_NOT_INSTALLED` or `INTEGRITY_FAILED` |
| **Object Detection** | Heuristic fallback only (3 classes) | Multi-class tensor parser + heuristic disclosure | **Verified Real** | Honestly discloses `real_weights_loaded=False` when weights absent |
| **Process Isolation** | Thread timeouts (`TERMINATION_UNCONFIRMED`) | Native OS process supervisor (`spawn` context) | **Verified Real** | True OS termination, generation epoch protection, stale result rejection |
| **Recording Continuity** | Unit test only | Verified under process crash / kill (Scenarios A-L) | **Verified Real** | 0 frame loss on `RecordingContinuityLedger` |
| **License Plate OCR** | Synthetic `frame_id` generator | Pixel contour & template cross-correlation | **Verified Real** | Reads actual pixels; blank plates return `OCR_RUNTIME_UNAVAILABLE` |
| **Speed Calibration** | Scalar $px/m$ only (foreshortening error) | $3\times3$ planar road homography | **Verified Real** | Projects image pixels to ground plane meters; uncalibrated returns `RELATIVE_MOVEMENT_ONLY` |
| **Discrete GPU Inference** | Claimed in docs, unverified | Disclosed as optional accelerator | **Gated / Deferred** | CPU-only Tier A is verified baseline; CUDA tested only when hardware present |
| **NPU Acceleration** | Architecture stubs | Disclosed as optional hardware target | **Deferred** | Requires dedicated NPU runtime; CPU fallback active |
| **Physical Field Soak** | Lab simulated | Accredited physical environmental soak | **Deferred** | Physical thermal chamber / 72h environmental testing requires third-party lab |

---

## 3. Residual Non-Critical Limitations

1. **Pre-Trained Weight Distribution:**
   - Pre-trained neural weights (e.g. YOLO/SSD ONNX files, ~45MB) are not bundled directly in the Git repository to keep repository size lean and respect vendor distribution policies. The system honestly discloses `MODEL_NOT_INSTALLED` when weights are not copied into `models/`.
2. **Debian/Linux OS Process Signals:**
   - Process termination via `SIGTERM` / `SIGKILL` was validated through Python's cross-platform `multiprocessing` implementation on Windows 11 Enterprise. Actual POSIX kernel signal delivery should be verified when an accredited Debian Linux hardware testbed is accessible.
