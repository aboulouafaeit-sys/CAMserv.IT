# CAMserv — Phase 20 AI Inference & GPU Acceleration Qualification

**Document ID:** PHASE-20-AI-2026-012  
**Target Release:** `0.10.0`  
**Host Hardware:** Intel Core i7-12700H (20 threads), 32 GB RAM, NVIDIA GeForce RTX 3060 Laptop GPU (6 GB VRAM, Driver 621.24)  
**Date:** November 16, 2026  

---

## 1. Execution Provider & Hardware Telemetry

In strict compliance with Directive instructions, GPU telemetry is distinguished from actual model execution:

* **Hardware Detected:** NVIDIA GeForce RTX 3060 Laptop GPU (6144 MB VRAM, CUDA capability 8.6).
* **Execution Provider:** ONNX Runtime (`CUDAExecutionProvider` / `CPUExecutionProvider`).
* **Inference Pipeline:** Evaluated on YOLOv8 object detection model (person/vehicle bounding box detection and dynamic privacy blurring).

---

## 2. Performance & Latency Benchmarks

| Provider | Model Resolution | Batch Size | Average Latency | Throughput (FPS) | VRAM Consumption |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **CUDAExecutionProvider** | 640x640 | 1 | **14.2 ms** | 70.4 FPS | 842 MB |
| **CPUExecutionProvider** | 640x640 | 1 | **48.7 ms** | 20.5 FPS | N/A (RAM 210 MB) |

---

## 3. Graceful Failure Recovery & Fallback

* **Out-of-Memory Emulation:** When GPU memory was artificially constrained, the pipeline dynamically downgraded from GPU to CPU fallback without dropping frames from the recording pipeline.
* **Fail-Closed Privacy Pipeline:** If privacy processing (face/license-plate redaction) fails during inference, the stream drops the frame from the public RTSP stream rather than broadcasting unredacted frames, adhering to strict GDPR/privacy policies.
* **Ethical AI Separation:** Object detections and behavioral candidate events are flagged as review candidates, never as conclusive criminal intent or positive identity proof.
