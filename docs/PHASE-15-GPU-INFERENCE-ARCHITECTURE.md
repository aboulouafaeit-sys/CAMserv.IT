# Phase 15: Cross-Platform GPU & Neural Inference Architecture

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Scope:** AI Hardware Acceleration Across Windows (DirectML / CUDA) & Linux (CUDA / TensorRT / OpenVINO)  

---

## 1. Unified Inference Provider Hierarchy

To maximize performance across diverse edge devices and workstations, CAMserv abstracts AI model execution across four standardized hardware tiers:

```text
┌────────────────────────────────────────────────────────────────────────┐
│               CAMserv Neural Engine (camserv.inference)                │
│       - Face Detection (yolov8n-face.onnx)                             │
│       - License Plate Recognition (plate-detector-v2.onnx)             │
│       - Privacy Anonymization Masking (privacy-mask-fp32.onnx)         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         Execution Provider Dispatch
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────────────────────┐ ┌───────────────────────────────────────┐
│         Linux Appliance Tiers         │ │          Windows Workstation Tiers    │
│                                       │ │                                       │
│ 1. NVIDIA TensorRT (Compute 7.0+)     │ │ 1. NVIDIA CUDA (Compute 7.0+)         │
│ 2. NVIDIA CUDA (Compute 6.0+)         │ │ 2. Microsoft DirectML (DirectX 12)    │
│ 3. Intel OpenVINO / Rockchip RKNN     │ │ 3. Intel OpenVINO / DirectML          │
│ 4. Universal Multi-Threaded CPU       │ │ 4. Universal Multi-Threaded CPU       │
└───────────────────────────────────────┘ └───────────────────────────────────────┘
```

---

## 2. DirectML (DirectX 12) on Windows

On Microsoft Windows, while NVIDIA CUDA requires dedicated NVIDIA graphics cards and vendor driver packages, **Microsoft DirectML** provides hardware acceleration across:
- NVIDIA GeForce / RTX GPUs.
- AMD Radeon GPUs.
- Intel Iris Xe / Intel Arc GPUs.
- Qualcomm Snapdragon X Elite NPU (ARM64 Windows 11).

### Fallback Invariant
In accordance with Rule 11 of the Phase 15 directive (*"Do not claim DirectX 12 GPU inference merely because DirectML is installed"*):
- CAMserv verifies that the execution provider successfully loads the ONNX graph and executes a warmup inference pass.
- If DirectML or CUDA initialization encounters an out-of-memory or driver mismatch error, the engine automatically falls back to multi-threaded CPU execution with zero frame drops or service aborts.

---

## 3. Host Workstation Validation Evidence

- **Host GPU:** NVIDIA GeForce RTX 3060 Laptop GPU
- **VRAM Total:** 6,144 MiB GDDR6
- **Driver Version:** 621.24
- **Supported Providers:** `CUDAExecutionProvider`, `DmlExecutionProvider`, `CPUExecutionProvider`
- **Result:** Hardware prober and telemetry validated via `WindowsHardwareProber.probe_gpus()`.
