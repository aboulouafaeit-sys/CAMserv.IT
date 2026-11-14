# CAMserv — AI Model & Open-Source License Register
**Phase:** 2 — Local AI & Edge Intelligence  
**Standard:** Production Security, Zero-Cloud API, Hardware-Agnostic  
**Integrity Enforcement:** Cryptographic SHA-256 Checksums  

---

## 1. Executive Summary

CAMserv operates strictly under an **Ultra-Local, Zero-API** operational paradigm. No frame data, embeddings, or biometric attributes are ever dispatched to external cloud endpoints. All neural network models execute on-premise using local hardware acceleration (NVIDIA TensorRT, CUDA, OpenVINO, DirectML) with guaranteed, tested CPU fallback.

This document serves as the formal registry of models, licensing conformity, operational parameters, and cryptographic hashes.

---

## 2. Certified Model Registry

| Model Identifier | Version | Computer Vision Task | Framework | License | Input Tensor | Output Tensor | SHA-256 Digest (Verified) | Provenance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **yolov8n-seg** | `1.0.0` | Instance Segmentation & Polygon Contouring | ONNX / TensorRT | AGPL-3.0 | `(1, 3, 640, 640)` | `[(1, 116, 8400), (1, 32, 160, 160)]` | `d5a49c32f22b9183492ffbb47cf9ee5582f30d075d9e525fa5001ff89309cb01` | Ultralytics Open-Source Local Export |
| **yolo11n-pose** | `1.0.0` | 17-Keypoint Skeletal Pose Analysis | ONNX / TensorRT | AGPL-3.0 | `(1, 3, 640, 640)` | `[(1, 56, 8400)]` | `7cb08f9f60f64b4c73de298d07ea589d89270bb383e58eecc04141d8a4ba1f31` | Ultralytics Open-Source Local Export |
| **face-plate-anonymizer** | `1.0.0` | Non-Biometric Face & License Plate Detection | ONNX | Apache-2.0 | `(1, 3, 640, 640)` | `[(1, 84, 8400)]` | `a84efc713b56740882e705b76b2510204df776bc384b655513d74c05872ea4e1` | CAMserv Edge Anonymization Model |
| **clahe-software-isp** | `1.0.0` | Low-Light Equalization & Denoising | OpenCV / NumPy | BSD-3-Clause | `(H, W, 3)` | `(H, W, 3)` | N/A (Algorithmic Deterministic Pipeline) | CAMserv Core Software ISP |

---

## 3. Strict Non-Biometric Policy & GDPR Article 9 Compliance

1. **Zero Biometric Identification:**  
   Models registered within CAMserv are restricted strictly to **category-level classification** (`person`, `vehicle`, `bicycle`, etc.), bounding boxes, and coarse polygon contours.
2. **Absence of Facial Recognition:**  
   Facial recognition models, facial embedding extractors, identity databases, and demographic profiling neural networks are explicitly prohibited from registration.
3. **Transient Integer Tracking:**  
   Object tracking assigns temporary stream-isolated integers (`track_id`). These identifiers expire automatically upon camera occlusion or departure and are never correlated across camera boundaries.

---

## 4. Software Supply Chain & Integrity Enforcement

Every model loaded into the `InferenceEngine` must be verified against the registered SHA-256 digest before session binding:

```python
computed_hash = metadata.calculate_file_hash()
if computed_hash.lower() != metadata.sha256_hash.lower():
    raise ModelIntegrityError("Tampered model weights detected. Refusing execution.")
```

If any weight file is altered, corrupted, or replaced with an unverified artifact, the system immediately halts model initialization, raises `ModelIntegrityError`, logs a critical security audit event, and transitions the pipeline to fail-closed safety state.
