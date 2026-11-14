# CAMserv — Phase 2 Architecture Specification
**Platform:** CAMserv Advanced Security Intelligence Platform  
**Phase:** 2 — Local AI & Edge Intelligence  
**Architecture Paradigm:** 100% Ultra-Local, Zero-API, Hardware-Agnostic, Privacy-Preserving  

---

## 1. System Overview

CAMserv Phase 2 elevates the platform from an isolated video ingestion and stream pipeline into an intelligent edge computer vision appliance. The design adheres strictly to the following architectural tenets:
1. **Zero External Cloud Dependencies:** All decoding, inference, tracking, threat scoring, and privacy masking operate on local edge hardware.
2. **Capability-Based Hardware Abstraction:** The platform inspects local CPU, CUDA, TensorRT, OpenVINO, and DirectML capabilities at boot and adapts dynamically without hard-coded hardware assumptions.
3. **Fail-Closed Privacy by Design:** The privacy pipeline guarantees that unmasked frames never leave the inference engine if detection models fail.
4. **Epistemic Transparency:** Inferences are strictly categorized as predictions with calibrated confidence bounds ($p \in [0.0, 1.0]$), preventing unverified assumptions.
5. **Non-Biometric Tracking:** Multi-object tracking assigns transient anonymous integer IDs scoped strictly to individual camera streams; cross-camera identity matching is structurally prohibited.
6. **Immutable Forensic Preservation:** Original video evidence is hashed and stored pristine; privacy masks and image enhancements are cryptographically signed derivatives.

---

## 2. Subsystem Architecture

```
                                  +---------------------------------------+
                                  |     RTSP / ONVIF Video Streams        |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |    Isolated Camera Worker Processes   |
                                  |   (Shared Memory Zero-Copy Ingestion) |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |    Adaptive Multi-Rate Scheduler      |
                                  |    (5 FPS Baseline / 30 FPS Burst)    |
                                  +-------------------+-------------------+
                                                      |
                       +------------------------------+-------------------------------+
                       |                                                              |
                       v                                                              v
       +-------------------------------+                              +-------------------------------+
       |       InferenceEngine         |                              |  ForensicEnhancementPipeline  |
       | - ModelRegistry (SHA-256)     |                              | - LAB CLAHE Luminance Equaliz.|
       | - Provider Hierarchy (TRT->   |                              | - Dynamic Contrast Stretch    |
       |   CUDA -> OpenVINO -> CPU)    |                              | - Bilateral Edge Denoising    |
       | - Bounded Queue Backpressure  |                              | - Side-by-Side Dual-Pane Comp.|
       | - Transparent CPU Fallback    |                              | - Pristine Raw Preservation   |
       +---------------+---------------+                              +---------------+---------------+
                       |                                                              |
                       v                                                              v
       +-------------------------------+                              +-------------------------------+
       |  MultiCameraTrackingCoord.    |                              |   FailClosedPrivacyPipeline   |
       | - Scoped Anonymous Track IDs  |                              | - Face & License Plate Masking|
       | - TENTATIVE -> CONFIRMED      |                              | - Gaussian / Mosaic / Solid   |
       | - OCCLUDED Recovery Window    |                              | - FAIL_CLOSED Global Masking  |
       | - Kinematics (Velocity/Speed) |                              | - PrivacyEvidenceManifest     |
       | - Cross-Camera Correlation Blk|                              |   (original_sha256/derivative)|
       +---------------+---------------+                              +---------------+---------------+
                       |                                                              |
                       +------------------------------+-------------------------------+
                                                      |
                                                      v
                                      +-------------------------------+
                                      |       BehavioralEngine        |
                                      | - Restricted Area Intrusion   |
                                      | - Perimeter Loitering Dwell   |
                                      | - Access Point Tampering      |
                                      | - Night Schedule Anomaly      |
                                      | - Retail Interaction Sequence |
                                      | - Human-in-the-Loop Review    |
                                      |   (DETECTED->UNDER_REVIEW->   |
                                      |    CONFIRMED / DISMISSED)     |
                                      +---------------+---------------+
                                                      |
                                                      v
                                      +-------------------------------+
                                      |      CinematicHUDRenderer     |
                                      | - Glassmorphic Telemetry Card |
                                      | - 3D Ground Perspective Rings |
                                      | - Dynamic Threat Aura (Cyan,  |
                                      |   Amber, Crimson)             |
                                      | - Skeletal Pose & Trails      |
                                      +-------------------------------+
```

---

## 3. Data Flow & Security Guarantees

1. **Ingestion to Inference:**  
   Workers write raw frames into shared memory slots (`shared_memory.py`). The `InferenceEngine` reads frames directly into pre-allocated memory buffers, eliminating inter-process serialization overhead.
2. **Integrity Enforcement:**  
   Before model weights are executed, their SHA-256 hash is compared against the certified `ModelRegistry`. If a mismatch is detected, the process aborts with `ModelIntegrityError`.
3. **Queue Backpressure:**  
   The inference queue maintains a maximum depth ($N \le 16$). When saturated, older frames are systematically dropped with `DROPPED` status to guarantee zero latency drift on live streams.
4. **Human Review Gate:**  
   Consequential actions (such as automated door lockouts or law enforcement dispatch) are gated by `BehavioralEngine`'s operator review workflow (`CONFIRMED` state with verified operator ID).
