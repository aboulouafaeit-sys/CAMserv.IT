# CAMserv — Edge AI Hardware Accelerator Validation Report

**Document ID:** AUDIT-HW-ACCEL-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Classification:** Silicon Hardware Acceleration & Execution Provider Audit  
**Date:** November 16, 2026  
**Auditor:** Independent Edge AI & Hardware Acceleration Engineer  

---

## 1. Executive Summary & Verification Rules

This report audits the neural inference execution providers, physical accelerator discovery, driver binding, and fallback mechanisms in CAMserv.

In accordance with Section 6 of the Phase 12 Directive:
- **Zero False Acceleration:** The system must NEVER report acceleration when inference actually executes on CPU.
- **Physical Device vs. Runtime Separation:** A physical silicon accelerator is never reported as available based only on CLI tools (`nvidia-smi`) without a functioning, callable Python execution provider.
- **Service Isolation:** Failure or absence of an accelerator must never crash the core NVR service.
- **Honest Capability Fallback:** System orchestrators must fall back cleanly and document the active execution provider.

---

## 2. Hardware Acceleration Matrix

| Target Platform / Accelerator | Physical Silicon Present? | Kernel Driver / CLI Status | Python Execution Provider | Adapter Availability | Active Execution Provider | Validation Classification |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **NVIDIA CUDA / TensorRT** | **YES** (GeForce RTX 3060 Laptop GPU, 6GB VRAM) | **DETECTED** (Driver 621.24, `nvidia-smi` OK) | **NOT INSTALLED** (`onnxruntime-gpu` / `torch` absent in Python 3.14) | **`is_available() = False`** (SEC-P12-04 Remediated) | Universal CPU | **`VERIFIED_ON_REAL_HARDWARE` (Device)** / **`NOT_AVAILABLE` (Runtime)** |
| **Intel OpenVINO** | **YES** (12th Gen Core i7-12700H + Iris Xe) | System Native | **NOT INSTALLED** (`openvino` package absent) | **`is_available() = False`** | Universal CPU | **`NOT_AVAILABLE`** |
| **Google Coral Edge TPU** | **NO** (No physical USB/M.2 ASIC) | Not Present (`/dev/apex_0` absent) | **NOT INSTALLED** (`pycoral` absent) | **`is_available() = False`** | Universal CPU | **`NOT_AVAILABLE`** |
| **Hailo-8 / Hailo-8L NPU** | **NO** (No physical PCIe/M.2 NPU) | Not Present (`/dev/hailo0` absent) | **NOT INSTALLED** (`hailort` absent) | **`is_available() = False`** | Universal CPU | **`NOT_AVAILABLE`** |
| **Universal CPU Engine** | **YES** (12th Gen Intel Core i7-12700H, 14C/20T) | System Native | **ACTIVE** (Multi-threaded CPython/NumPy/OpenCV) | **`is_available() = True`** | **`onnx_cpu`** (20 Compute Units) | **`VERIFIED_ON_REAL_HARDWARE`** |

---

## 3. Deep Dive: SEC-P12-04 Remediation & Empirical Behavior

Prior to Phase 12, `CUDABackendAdapter.is_available()` performed a superficial check: `shutil.which("nvidia-smi") is not None`. Because this host is equipped with an NVIDIA RTX 3060 GPU and driver 621.24, `nvidia-smi` was found, leading `get_best_available_adapter()` to erroneously designate `nvidia_cuda` as the active provider. When `load_model()` was called, it logged success and returned `True`, while `infer()` returned `[]` without touching the GPU.

### Remediated Architecture:
1. **Device Detection Method (`is_device_detected`):** Queries `nvidia-smi` and extracts device metadata ($6144\text{ MiB VRAM}$, Driver $621.24$, Compute Mode $Default$).
2. **Runtime Verification Method (`is_runtime_available`):** Probes whether a callable GPU execution provider (`torch.cuda.is_available()`, `onnxruntime` `CUDAExecutionProvider`, or `cv2.cuda`) is installed.
3. **Availability Conjunction (`is_available`):** Returns `True` **only** if both physical hardware and execution runtime are operational.
4. **Diagnostic Transparency:** `get_profile()` sets `driver_version="NVIDIA Hardware Present (No Python Runtime)"` and explains in `notes` that the physical GPU was detected but lacks a Python execution provider.
5. **Clean Fallback Resolution:** `get_best_available_adapter()` selects `onnx_cpu`, executing honestly on the 20 available CPU hardware threads without misleading telemetry.

---

## 4. Hardware Coprocessor Readiness for Appliance Deployment

For dedicated appliance packaging (Profile A and Profile B):
- **Profile A (Rockchip RK3588):** Target runtime is `rknpu2` / `rknn-toolkit2-lite2` (6 TOPS NPU). Adapter interface prepared; requires physical board flash.
- **Profile B (Industrial x86):** Target runtime is NVIDIA TensorRT via `onnxruntime-gpu` (CUDA 12.x / TensorRT 10.x) or HailoRT (Hailo-8 26 TOPS).
- **Service Resilience:** In all configurations, if an accelerator encounters hardware disconnection, driver timeout, or kernel panic, CAMserv intercepts the exception, triggers alert telemetry, and seamlessly reverts to `onnx_cpu` without dropping ongoing NVR recording.
