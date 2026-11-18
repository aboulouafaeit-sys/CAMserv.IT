# CAMserv Phase 27.2 — Real Object Detection Integration Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Gate 27.2-A  
**Architecture:** Single Organization / Local-First Deployment  
**Audited Component:** `src/camserv/intelligence/detection.py`

---

## 1. Executive Summary

Phase 27.1 established that `ObjectDetectionEngine` fell back unconditionally to `_detect_heuristic`, cycling deterministically between 3 simulated categories (`person`, `car`, `bicycle`). Genuine neural network tensor output parsing was absent.

In Gate 27.2-A, `ObjectDetectionEngine` was upgraded to parse genuine multi-class output tensors from OpenCV DNN models (supporting SSD `1x1xNx7` and YOLO `1xNxM` formats), separate real neural detections from diagnostic fallback heuristics, and honestly disclose execution metadata.

---

## 2. Multi-Class Tensor Parsing & Real Inference

In `src/camserv/intelligence/detection.py`:
- `_detect_dnn(frame, camera_id, frame_id, ts)`:
  1. Computes standardized normalized input blob via `cv2.dnn.blobFromImage`.
  2. Sets tensor to network and executes `self._net.forward()`.
  3. Measures precise forward pass latency in milliseconds (`latency_ms`).
  4. Parses real bounding boxes $(x_1, y_1, x_2, y_2)$ and per-class confidences.
  5. Maps class indices to the canonical class taxonomy.
  6. Applies Non-Maximum Suppression (NMS) with configurable IoU threshold (default 0.45).
  7. Returns predictions with metadata:
     - `is_simulated_heuristic: False`
     - `real_weights_loaded: True`
     - `model_id: str`
     - `backend: str`
     - `latency_ms: float`

---

## 3. Honest Epistemic Fallback Disclosure

To eliminate ambiguity between simulated output and neural network inference:
- The engine supports `allow_heuristic_fallback: bool` (default `True` for CI/offline environments).
- When neural weights are absent and fallback is enabled:
  - All predictions carry `is_simulated_heuristic: True` and `real_weights_loaded: False`.
  - The metadata explicitly records `heuristic: "luminance_contrast_geometry"`.
- When `allow_heuristic_fallback: False`:
  - The engine returns an empty list (`[]`).
  - No synthetic detections or simulated bounding boxes are generated.

---

## 4. Canonical Class Taxonomy Prioritization

The platform maintains the 16 canonical categories defined in Phase 27:
- **Priority Initial Categories (6):** `person`, `car`, `motorcycle`, `bicycle`, `bus`, `truck`.
- **Secondary & Hazard Categories (10):** `pedestrian`, `crowd`, `scooter`, `van`, `emergency_vehicle`, `animal`, `road_obstruction`, `fallen_object`, `smoke`, `fire`.

When real weights are loaded, active classes are restricted to `model_record.supported_classes`.

---

## 5. Verification Evidence

In `tests/test_phase27_2_real_ai_and_process_isolation.py`:
- `test_detection_engine_metadata_and_heuristic_fallback_transparency()`: PASS.
- `test_canonical_classes_taxonomy()` in `test_phase27_detection_classification.py`: PASS.
- Total detection tests: 5 / 5 passing.
