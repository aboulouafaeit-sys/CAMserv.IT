# Phase 1E Hardware Capability Discovery & Abstraction Report
**Document ID:** P1E-HW-2026-001  
**Author:** Edge Inference Acceleration & Platform Hardware Specialist  
**Date:** November 14, 2026  
**Status:** **PHASE 1E ACCEPTED**  
**Target:** Explicit diagnostic status taxonomy, hardware decode probing, and zero-assumption execution abstraction.

---

## 1. Architectural Scope & Purpose

To ensure that CAMserv deploys seamlessly across diverse compute envelopes—from low-power edge nodes to dedicated GPU surveillance appliances—Phase 1E introduces a capability-driven hardware discovery and abstraction subsystem.

The platform never assumes that CUDA, NVDEC, or proprietary SDKs exist. Instead, it inspects host capabilities at startup, maps resources to standardized diagnostic states, and configures the optimal combination of video decode and neural inference backends.

---

## 2. Diagnostic State Taxonomy (`DiagnosticState`)

All hardware accelerators and execution pipelines report status using a standardized 5-tier state enum:

| State | Definition | Architectural Behavior |
| :--- | :--- | :--- |
| **`AVAILABLE`** | Hardware block detected, initialized, and operating normally. | Enabled for primary workload execution. |
| **`ACTIVE`** | The hardware engine currently selected as the active provider. | Primary inference / decode pipeline. |
| **`UNAVAILABLE`** | Hardware block absent on the host machine. | Clean fallback to software provider (e.g. CPU `libavcodec` / `onnx_cpu`). |
| **`DEGRADED`** | Hardware present but constrained (e.g. VRAM $< 4$GB, driver out-of-date, thermal throttling). | Streams capped to safe concurrency threshold (e.g. 2–3 streams); memory-heavy features disabled. |
| **`UNSUPPORTED`** | Hardware present but architectural compute capability $< 6.0$. | Blocked from neural inference to avoid unstable numerical errors or unsupported FP16/INT8 ops. |

---

## 3. Video Decode & Neural Backend Mapping

### 3.1 Hardware Video Decoding (`DecoderCapability`)
The platform discovers and exposes hardware-accelerated decoders:
* **`nvdec` (NVIDIA Silicon):** Primary decoder on hosts with supported NVIDIA GPUs (H.264, HEVC, VP9).
* **`dxva2` (Windows Video Acceleration):** Hardware decode on Windows workstations.
* **`vaapi` (Linux Video Acceleration API):** Hardware decode on Linux systems with Intel/AMD/NVIDIA drivers.
* **`software` (CPU Fallback):** Universal `libavcodec` fallback ensuring zero-failure startup.

### 3.2 Host Diagnostic Health Profile
`HardwareDetector.probe_host()` builds an integrated `HardwareDiagnostics` matrix within `HardwareProfile`:
```python
@dataclass(slots=True)
class HardwareDiagnostics:
    gpu_state: DiagnosticState
    tensorrt_state: DiagnosticState
    decoders: list[DecoderCapability]
    active_decoder: str
    active_inference_backend: str
```

---

## 4. Verification & Acceptance Evidence

Automated test suite `tests/test_hardware_diagnostics.py` passed with 100% success:
1. `test_diagnostic_states_enumeration`: Validated `AVAILABLE`, `ACTIVE`, `UNAVAILABLE`, `DEGRADED`, `UNSUPPORTED`.
2. `test_hardware_profile_diagnostics_live_host`: Probed host environment, verified diagnostic health reporting and decoder capabilities.
3. `test_simulated_degraded_gpu_state`: Verified low-VRAM GPU correctly transitions to `DEGRADED`.
4. `test_simulated_unsupported_gpu_state`: Verified legacy compute capabilities ($< 6.0$) are rejected with `UNSUPPORTED`.
5. `test_decoder_capability_attributes`: Verified codec metadata and driver bindings.
