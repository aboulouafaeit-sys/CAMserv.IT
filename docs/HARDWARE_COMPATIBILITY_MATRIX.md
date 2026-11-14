# CAMserv Universal Hardware Compatibility Matrix & Adaptation Plan
**Document ID:** HW-MATRIX-2026-001  
**Author:** Principal Infrastructure Engineer & Hardware Performance Architect  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Operational Tiers:** 4 Defined Hardware Profiles (Edge CPU to Enterprise Multi-GPU)

---

## 1. Operational Hardware Tiers

CAMserv's automatic hardware prober inspects host CPU topology, RAM availability, CUDA capability, and VRAM bandwidth during boot, dynamically locking the runtime into the optimal tier:

| Parameter | Tier 1: Edge CPU | Tier 2: Balanced | Tier 3: Performance | Tier 4: Enterprise Cluster |
|---|---|---|---|---|
| **Target Hardware** | Edge IPCs / Intel N100 / Raspberry Pi 5 | Quad-Core i5/i7 / Ryzen 5 (No GPU) | NVIDIA RTX 3060/4060 (6-8 GB VRAM) | Multi-GPU RTX 4090 / A5000 / H100 |
| **Max Concurrent Streams** | 2–4 Streams (720p @ 15 FPS) | 4–8 Streams (1080p @ 20 FPS) | 8–16 Streams (1080p @ 30 FPS) | 32–64 Streams (4K/1080p @ 30 FPS) |
| **Decoding Backend** | CPU / Intel QuickSync / VAAPI | CPU / QuickSync / VAAPI | NVIDIA NVDEC (Hardware Surface) | Dual NVDEC Engines + Dedicated Decoders |
| **Inference Runtime** | ONNX Runtime CPU / OpenVINO | ONNX Runtime CPU (AVX2/AVX-512) | TensorRT / ONNX Runtime CUDA (FP16) | TensorRT Multi-Stream Contexts (INT8) |
| **Active Models** | Heuristic Motion + YOLOv8n (5 FPS) | YOLOv8n Detection (10 FPS) | YOLOv8n-seg + YOLOv8n-pose (Full Rate) | YOLOv11s-seg + Pose + RT-DETR |
| **Software ISP** | Bypassed (Passthrough) | Selective ROI CLAHE (Low Light only) | Full LAB CLAHE on all streams | Full LAB CLAHE + Temporal Denoising |
| **RAM Requirement** | 4 GB Minimum (8 GB Recommended) | 8 GB Minimum (16 GB Recommended) | 16 GB Minimum (32 GB Recommended) | 64 GB Minimum (128 GB Recommended) |
| **VRAM Requirement** | N/A (Shared RAM $< 1\text{ GB}$) | N/A (Shared RAM $< 2\text{ GB}$) | 6 GB Dedicated VRAM | 16 GB - 48 GB Dedicated VRAM |

---

## 2. Dynamic Pressure-Shedding Watchdog

Under environmental temperature spikes, resource contention, or sudden crowd surges, CAMserv prevents system freeze through autonomous 3-level load shedding:

```
[Normal Operation: Full FPS & Resolution]
               |
               v (CPU > 85% or FPS drop > 30% for 5s)
[Level 1 Shedding: Reduce Analytical Sampling Rate by 50%]
  - Ingestion continues at 30 FPS for recording
  - Inference runs on every 2nd frame (15 FPS)
               |
               v (RAM > 90% or VRAM OOM Warning)
[Level 2 Shedding: Downscale Inference Tensor to 480x480 & Disable Pose]
  - Halts 17-keypoint skeletal stick figure calculation
  - Reduces neural tensor footprint by 44%
               |
               v (Critical Disk or Thermal Threshold)
[Level 3 Shedding: Enter Emergency Ingestion-Only Mode]
  - Suspends analytical inference pipeline completely
  - 100% compute dedicated to RTSP capture, pre-roll vault, and operator live feeds
```

---

## 3. Storage I/O & Memory Budgets

* **RAM Pre-Roll Ring Buffer:**
  - $1920 \times 1080$ @ 15 FPS H.264 GOP $= 15\text{ frames/sec} \times 15\text{ seconds} = 225\text{ frames}$.
  - At an encoded bitrate of $4\text{ Mbps}$, 15 seconds of RAM pre-roll occupies only $\approx 7.5\text{ MB}$ per camera.
  - An 8-camera system requires $< 60\text{ MB}$ of total RAM for pre-roll buffers.
* **Disk Write Amplification Protection:**
  - In absence of verified threats, CAMserv records routine video in low-bitrate Tier 1 storage ($1.5\text{ Mbps}$).
  - High-bitrate forensic recording ($8\text{ Mbps}$) triggers ONLY upon verified threat score $T \ge 70$.
