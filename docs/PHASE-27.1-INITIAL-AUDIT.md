# CAMserv — Phase 27.1: Initial Repository Audit & Adversarial Baseline Inspection

**Document ID:** AUDIT-P27.1-BASELINE-2026-029  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Expected Baseline:** `c62c1271fbe1aa53fd018d9deaa3eaa7d5ab7942`  
**Actual Git HEAD:** `c62c1271fbe1aa53fd018d9deaa3eaa7d5ab7942`  
**Branch:** `main`  
**Audit Date:** November 18, 2026  
**Auditor Roles:** Principal Adversarial Security Auditor, Computer Vision Quality Engineer, Storage Reliability Engineer & Systems Verification Specialist  

---

## 1. Executive Summary

This document establishes the official starting baseline inspection for **Phase 27.1: Adversarial Verification, Real-World Vision Accuracy & Recording Isolation Audit**.

The repository was inspected to verify that HEAD strictly matches commit `c62c1271fbe1aa53fd018d9deaa3eaa7d5ab7942`. The working tree contains Phase 27 implementations in `src/camserv/intelligence/`, test suites in `tests/test_phase27_*.py`, and Phase 27 qualification documentation in `docs/`.

All 648 automated test cases currently pass cleanly in CI. However, this adversarial audit moves beyond nominal test execution to interrogate the physical reality of the vision engines, worker isolation mechanics, tracking continuity, speed measurement claims, and recording pipeline inviolability.

---

## 2. Baseline & Invariant Inspection

### 2.1 Git Repository Invariants
* **Repository Path:** `C:\Users\MPront\Documents\CAMserv`
* **Current Branch:** `main`
* **Current HEAD Commit:** `c62c1271fbe1aa53fd018d9deaa3eaa7d5ab7942`
* **Baseline Match:** **CONFIRMED (100% IDENTICAL)**
* **Git Policy:** Strict read-only enforcement. Zero commits, zero pushes, zero tags, zero resets, zero merges.

### 2.2 Critical Physical File Invariants
* **Audit Log (`logs/audit.jsonl`):**
  - Expected Length: Exactly 20,977 bytes
  - Actual Length: Exactly 20,977 bytes
  - Expected SHA-256: `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`
  - Actual SHA-256: `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`
  - Invariant Status: **INVIOLATE (0 BYTES MUTATED)**
* **Official Branding Assets:**
  - Asset Registry: Exactly 34 official branding assets (24 in `assets/branding/`, 10 in `src/camserv/web/assets/`).
  - Web Console Header: `src/camserv/web/index.html` (lines 17–23) and `styles.css` (lines 160–205) retain the official 38px logo and telemetry pills intact.

---

## 3. Preliminary Reality Audit: Discrepancies & Audit Scope

A deep code inspection of `src/camserv/intelligence/` revealed 6 critical engineering realities that must be independently challenged and remediated during Phase 27.1:

| Component | Reported Claim | Actual Code Reality | Severity |
| :--- | :--- | :--- | :---: |
| **Object Detection (`detection.py`)** | "OpenCV DNN model inference across 16 canonical classes" | Model weight file `models/camserv_detector_v1.onnx` is **ABSENT** on disk. Detection executes a center-crop luminance simulator cycling between person/car/bicycle. 13 classes are uncallable. | **CRITICAL** |
| **Worker Isolation (`scheduler.py`)** | "Hard 2.0s worker timeout provides complete failure isolation" | `ThreadPoolExecutor` timeout releases the caller, but the underlying worker thread **REMAINS BLOCKED** in the background. State is `TERMINATION_UNCONFIRMED`. | **CRITICAL** |
| **Vehicle Speed (`traffic.py`)** | "Calibrated vehicle speed in km/h" | Speed is calculated using a uniform scalar `pixels_per_meter`, which ignores perspective foreshortening in downward-angled cameras. Homography ground-plane transformation is unused. | **HIGH** |
| **License Plate OCR (`anpr.py`)** | "12-stage OCR extraction and character-level confidence" | Optical quality gating is real, but OCR extraction calls `_deterministic_plate_ocr` which synthesizes characters from `frame_id`. No neural/Tesseract OCR engine is active. | **HIGH** |
| **Model Registry (`registry.py`)** | "Cryptographic SHA-256 weight integrity" | `expected_sha256` is `e3b0c44298fc1c14...`, which is the standard SHA-256 hash of an **EMPTY 0-BYTE FILE**. | **MEDIUM** |
| **Admission Control (`scheduler.py`)** | "AI tasks shed at 90% CPU/RAM load" | Static boundary lacks hysteresis damping. An oscillating host (89.9% to 90.1%) triggers rapid admission/shedding thrashing. | **MEDIUM** |

---

## 4. Phase 27.1 Action Plan

1. **Adversarial Audit Reports:** Complete dedicated audits across Object Detection (Audit A), Tracking (Audit B), Traffic & Speed (Audit C), ANPR (Audit D), Worker Isolation & Recording Protection (Audit E), Scheduler & Hysteresis (Audit F), and Model Registry (Audit G).
2. **Engineering Hardening:**
   - Formalize worker lifecycle states (`RUNNING`, `CANCELLATION_REQUESTED`, `TERMINATION_UNCONFIRMED`, `TERMINATED`, `RESTART_PENDING`, `RECOVERY_FAILED`).
   - Implement scheduler admission hysteresis (e.g. shed at 90%, recover at 80%).
   - Add perspective calibration validity flags (`CALIBRATED_ACCURATE`, `RELATIVE_MOVEMENT_ONLY`, `SPEED_UNAVAILABLE`).
   - Add Kalman velocity prediction projection to tracker bounding box matching.
   - Enforce explicit epistemic metadata labeling for simulated vs neural detections.
3. **Adversarial Test Suite:** Implement reproducible adversarial pytest suites verifying all failure modes and recording isolation invariants.
