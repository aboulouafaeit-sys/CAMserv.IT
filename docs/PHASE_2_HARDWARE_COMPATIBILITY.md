# CAMserv — Hardware Adaptation & Multi-Tier Execution Matrix
**Phase:** 2 — Local AI & Edge Intelligence  
**Standard:** Universal Hardware Compatibility, Zero-Assumption Deployment  

---

## 1. Operational Hardware Tiers

CAMserv dynamically identifies hardware capabilities at application initialization through `camserv.platform.hardware` and assigns the node to an operational tier.

| Tier | Profile Description | Minimum Specifications | Primary Inference Provider | Camera Capacity | Adaptive Analytics Profile |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | Enterprise AI Workstation / Multi-GPU Server | 16+ CPU Cores, 64 GB RAM, NVIDIA RTX 4090 / A100 / H100 | `TensorrtExecutionProvider` | 16-32 Streams | 30 FPS Burst, Full Contouring & Pose on all streams |
| **Tier 2** | Commercial Security Server / Edge GPU Appliance | 8-16 CPU Cores, 32 GB RAM, NVIDIA RTX 3060 / 4060 / T4 | `CUDAExecutionProvider` | 8-16 Streams | 5 FPS Baseline, 30 FPS Burst on threat detection |
| **Tier 3** | Mid-Range Office PC / NUC / Embedded Edge | 4-8 CPU Cores, 16 GB RAM, Intel Iris Xe / AMD Radeon | `OpenVINOExecutionProvider` or `DmlExecutionProvider` | 4-8 Streams | 5 FPS Baseline, 15 FPS Burst, Selective CLAHE |
| **Tier 4** | Legacy Server / Budget Edge Appliance | 2-4 CPU Cores, 8 GB RAM, Integrated / Pure CPU | `CPUExecutionProvider` | 1-4 Streams | 2-5 FPS Dynamic Fair-Share, Drop-Oldest Queuing |

---

## 2. Dynamic Provider Fallback Lifecycle

```
    [Boot Probing]
          |
          v
  Is TensorRT supported? ---> YES ---> Bind TensorrtExecutionProvider
          | NO
          v
  Is CUDA supported? --------> YES ---> Bind CUDAExecutionProvider
          | NO
          v
  IsOpenVINO / DML supported? > YES ---> Bind OpenVINO / DirectML
          | NO
          v
  Bind CPUExecutionProvider (Guaranteed Baseline)
```

### Runtime Degradation Handling
If a runtime error occurs during active GPU inference (e.g., CUDA Out of Memory or driver reset):
1. `InferenceEngine` intercepts the exception.
2. The hardware diagnostic state for the GPU is flagged as `DiagnosticState.DEGRADED`.
3. The engine increments `tracker.record_fallback()`.
4. The inference session immediately rebinds to `CPUExecutionProvider` without dropping the camera connection or crashing worker processes.
