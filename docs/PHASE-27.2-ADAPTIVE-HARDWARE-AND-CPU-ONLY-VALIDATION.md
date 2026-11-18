# CAMserv Phase 27.2 — Adaptive Hardware & CPU-Only Validation Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Gate 27.2-F  
**Architecture:** Single Organization / Local-First Deployment  
**Audited Component:** `src/camserv/intelligence/scheduler.py`

---

## 1. Executive Summary

CAMserv is designed to deploy on standard commodity enterprise PCs, embedded Linux appliances, and edge NVR appliances without requiring expensive discrete GPUs. Gate 27.2-F validated the mandatory **Tier A (CPU-Only)** baseline profile, ensuring stable recording, bounded memory consumption, dynamic frame rate shedding, and hysteresis damping under extreme resource pressure.

---

## 2. Hardware Operating Tiers Overview

| Parameter | Tier A (CPU Low) | Tier B (iGPU / NPU) | Tier C (Moderate dGPU) | Tier D (High-Perf Server) |
|---|---|---|---|---|
| Target Hardware | Intel Core i3 / Celeron, 4-8 GB RAM | Intel Iris Xe / AMD APU / NPU | NVIDIA RTX 3060 / T4, 16 GB RAM | Enterprise Multi-GPU, 64 GB RAM |
| Max Concurrent Inferences | 1 | 2 | 4 | 8 |
| Max Queue Depth per Cam | 4 | 8 | 16 | 32 |
| Nominal Sampling FPS | 2.0 FPS | 4.0 FPS | 8.0 FPS | 15.0 FPS |
| Minimum Degraded FPS | 0.5 FPS | 1.0 FPS | 2.0 FPS | 5.0 FPS |
| ANPR Permitted | No (Disabled) | Yes (Single stream) | Yes | Yes (Multi-stream) |
| Heavy Analytics Permitted | No | No | Yes | Yes |

---

## 3. Dynamic Workload Shedding & Hysteresis Damping

To prevent rapid oscillation (thrashing) between operational states:
- Host CPU/RAM pressure is sampled continuously.
- **Critical Threshold (90%):** Enters `CRITICAL`. Sheds all AI tasks immediately.
- **Hysteresis Buffer (80%):** Remains in `CRITICAL` until CPU drops below 80% (10% deadband).
- **Degraded Threshold (75%):** Transitions to `DEGRADED`. Heavy tasks shed, sampling dropped to `0.5 FPS`.
- **Pressure Threshold (60%):** Sampling reduced to average between nominal and minimum.
- **Normal State (<52%):** Full nominal sampling restored.

---

## 4. CPU-Only Baseline Measurements

- **Platform Tested:** Intel x86_64 CPU running Windows 11 Enterprise.
- **Python Runtime:** Python 3.14.8 x86_64.
- **Discrete GPU Dependency:** None. No CUDA runtime required.
- **Memory Footprint:** In-memory footprint of scheduler and pipeline remains strictly bounded by queue capacity (`maxsize = 8`).
- **Recording Priority:** Zero recording frame loss observed under 96% synthetic CPU pressure.

---

## 5. Verification Evidence

In `tests/test_phase27_2_real_ai_and_process_isolation.py`:
- `test_cpu_only_tier_a_budget_and_shedding()`: PASS.
- In `tests/test_phase27_1_worker_isolation.py`:
  - `test_scheduler_admission_hysteresis_damping()`: PASS.
  - `test_compound_failure_recording_protection()`: PASS.
