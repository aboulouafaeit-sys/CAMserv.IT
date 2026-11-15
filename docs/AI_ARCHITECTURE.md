# CAMserv AI & Computer Vision Architecture

**Document ID:** ARCH-AI-2026-001  
**Classification:** Technical Architecture Specification  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Overview and Core Principles

The **CAMserv AI** engine is a modular, hardware-adaptive computer vision and behavioral intelligence platform. It processes real-time video frames to detect objects, analyze trajectories, monitor virtual security zones, evaluate camera health, and generate reviewable security event candidates.

### Non-Negotiable AI Principles:
1. **Model & Hardware Independence:** Core functionality is decoupled from specific proprietary frameworks, running efficiently across CPU, CUDA, DirectML, OpenVINO, Coral Edge TPU, and Hailo-8.
2. **Strict Non-Biometric Enforcement:** Facial recognition, biometric templates, and cross-camera personal re-identification are prohibited at the architectural level.
3. **Epistemic Humility:** Algorithmic outputs are flagged as hypotheses (`is_prediction: true`) with bounded confidence ($0.0 - 1.0$).
4. **Behavioral Triage, Not Accusations:** Threat scores represent operator review priority rather than legal assessments of intent. Automated physical action without human operator confirmation is programmatically blocked.

---

## 2. Multi-Backend Hardware Adaptation

```
                            ┌──────────────────────────────────┐
                            │    Ingested Operational Frame    │
                            └────────────────┬─────────────────┘
                                             │
                                             ▼
                            ┌──────────────────────────────────┐
                            │     Hardware Capability Probe    │
                            │      (CPU / GPU / TPU / NPU)     │
                            └────────────────┬─────────────────┘
                                             │
         ┌───────────────────┬───────────────┴───────────────┬───────────────────┐
         ▼                   ▼                               ▼                   ▼
┌─────────────────┐ ┌─────────────────┐             ┌─────────────────┐ ┌─────────────────┐
│  CPU Execution  │ │  NVIDIA CUDA /  │             │  Intel OpenVINO │ │ Google Coral /  │
│ (ONNX Runtime)  │ │ TensorRT Engine │             │  (iGPU / VPU)   │ │  Hailo-8 NPU    │
└────────┬────────┘ └────────┬────────┘             └────────┬────────┘ └────────┬────────┘
         │                   │                               │                   │
         └───────────────────┴───────────────┬───────────────┴───────────────────┘
                                             ▼
                            ┌──────────────────────────────────┐
                            │    Standard Detection Output     │
                            │ (BBoxes, Polygons, Confidences)  │
                            └──────────────────────────────────┘
```

The system dynamically loads the optimal execution provider:
- **NVIDIA Hardware:** Uses TensorRT or CUDA provider for high-throughput batch inference.
- **Intel Hardware:** Uses OpenVINO provider for integrated GPUs and Neural Compute Sticks.
- **Edge AI Accelerators:** Uses Coral Edge TPU (libedgetpu) or Hailo-8 RT adapters.
- **Generic x86 / ARM:** Falls back gracefully to optimized ONNX Runtime CPU execution.

---

## 3. Detection, Segmentation & Tracking Pipeline

### 3.1 Object Detection & Segmentation
- Models: YOLOv8-seg and YOLOv11-seg instance segmentation.
- Classes: Person, vehicle (car, truck, bus, motorcycle, bicycle), animal (dog, cat), and unattended luggage/backpack.
- Outputs: Precise polygon contour vertices and ground-contact ellipses rather than coarse bounding boxes.

### 3.2 Anonymous Tracking (ByteTrack & BoT-SORT)
- Tracking Algorithm: Kalman filter kinematic projection with two-stage Hungarian association (high-confidence matches followed by low-confidence recovery).
- Identity Bounds: Track IDs are strictly integer sequences ($1, 2, 3\dots$) scoped solely to the observing camera. When a subject leaves the frame, the track ID is terminated.

### 3.3 Zone Analytics & Behavioral Intelligence (`camserv.analytics.zones`)
- **Tripwire (Line Crossing):** Computes intersection vectors between successive object ground-contact points and user-defined directed line segments.
- **Polygon Inclusion (Entry / Exit):** Uses ray-casting point-in-polygon algorithms to detect intrusion into sensitive security zones.
- **Loitering Detection:** Tracks stationary or low-velocity dwell times inside restricted polygons, triggering event candidates after exceeding threshold durations.
- **Crowd Density Estimation:** Aggregates concurrent pedestrian footprints to calculate real-time occupancy and flow density.

### 3.4 Camera Tampering & Scene Shift Detection (`camserv.analytics.tampering`)
- **Lens Obstruction:** Detects sudden drops in spatial variance and edge density (indicating spray paint, cloth, or physical covering).
- **Camera Defocus / Blur:** Monitors high-frequency Laplacian variance to flag intentional tampering or severe dirt accumulation.
- **Sudden Scene Shift:** Flags sudden high optical flow displacement without corresponding object detections (indicating physical camera redirection).
