# CAMserv Technology Evaluation & Selection Matrix
**Document ID:** TECH-EVAL-2026-001  
**Author:** Chief Software Architect & Technology Strategy Lead  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Decision Criteria:** Edge Performance, License Freedom (MIT/Apache 2.0), Concurrency Isolation, Zero Cloud Lock-in

---

## 1. Video Ingestion & Decoding Subsystem

| Technology Candidate | Throughput & Latency | Hardware Decode (NVDEC) | Process Isolation | Licensing | Architectural Decision |
|---|---|---|---|---|---|
| **OpenCV VideoCapture (Current)** | Moderate ($280\text{ms}$ Latency) | Requires Custom CUDA Build | Poor (GIL Thread Contention) | Apache 2.0 | **REPLACE:** Lacks robust RTSP transport control and crash resilience. |
| **FFmpeg Subprocess Pipeline** | Exceptional ($95\text{ms}$ Latency) | Native Hardware Flags (`-hwaccel cuda`) | Perfect (Dedicated OS Subprocess) | LGPL / GPL | **RECOMMENDED (PRIMARY):** Supervised subprocess with pipe to `/dev/shm`. |
| **GStreamer C Bindings** | High ($110\text{ms}$ Latency) | Native (`nvh264dec` / `vaapidecode`) | Moderate (Requires C extensions) | LGPL 2.1 | **EVALUATED:** Excellent for complex Linux NVRs, higher deployment complexity. |
| **libmpv Python Wrapper** | Moderate ($180\text{ms}$ Latency) | Supported | Poor (Shared Process Space) | GPL v2+ | **REJECTED:** Inflexible pipeline integration for raw frame tensor access. |

---

## 2. Edge Neural Inference Runtimes

| Runtime Candidate | GPU Acceleration (CUDA) | CPU Optimization (AVX) | Memory Overhead | Portability | Architectural Decision |
|---|---|---|---|---|---|
| **ONNX Runtime (Current)** | High (via CUDA Execution Provider) | Exceptional (via OpenVINO / CPU EP) | Low ($< 150\text{ MB}$) | Universal (Windows/Linux/ARM) | **RETAIN (PRIMARY GENERAL):** Ideal for Tier 1 to Tier 3 deployments. |
| **NVIDIA TensorRT** | Maximum ($2.5\times$ ONNX CUDA) | N/A (GPU Only) | Moderate ($< 300\text{ MB}$) | NVIDIA GPUs Only | **RECOMMENDED (TIER 3 & 4):** FP16/INT8 compiled execution engines. |
| **OpenVINO Runtime** | Intel GPUs Only | Industry-Leading on Intel CPUs | Low ($< 120\text{ MB}$) | Intel Architectures Only | **RECOMMENDED (TIER 1 & 2 INTEL):** Native acceleration for edge N100 IPCs. |
| **PyTorch Native** | High | Moderate | Excessive ($> 1.2\text{ GB}$) | Universal | **REJECTED FOR PRODUCTION INFERENCE:** High memory footprint and runtime overhead. |

---

## 3. Telemetry & Evidence Data Persistence

| Storage Candidate | Write Throughput | Forensic Immutability | Operational Footprint | Recovery Speed | Architectural Decision |
|---|---|---|---|---|---|
| **SQLite (WAL Mode - Current)** | High ($50,000\text{ writes/s}$) | Excellent (Atomic Single File) | Zero Daemon ($< 15\text{ MB}$) | Instantaneous | **RETAIN (PRIMARY EDGE STORAGE):** Zero administrative overhead and robust ACID. |
| **PostgreSQL / TimescaleDB** | Extreme ($200,000\text{ writes/s}$) | Excellent | Heavy Daemon ($> 500\text{ MB}$) | Moderate | **RECOMMENDED (TIER 4 ENTERPRISE CLUSTERS):** For multi-node fleet clustering. |
| **Embedded RocksDB / LMDB** | Extreme ($300,000\text{ writes/s}$) | High | Minimal ($< 30\text{ MB}$) | Fast | **EVALUATED:** Fast key-value index for multi-camera vector timelines. |

---

## 4. Frontend & Operator Console Architecture

| Framework Candidate | Bundle Size | Runtime Performance | Maintenance Burden | Offline Capability | Architectural Decision |
|---|---|---|---|---|---|
| **Modern Native JS / CSS (Current)** | Tiny ($< 80\text{ KB}$ gzipped) | Maximum (Direct DOM / Canvas) | Very Low (Zero build toolchain) | 100% Offline Embedded | **RETAIN & REFINE:** Exceptional responsiveness, instant load, zero NPM vulnerabilities. |
| **React 19 + Vite** | Moderate ($450\text{ KB}$) | High | High (Frequent ecosystem updates) | Supported | **REJECTED FOR EMBEDDED CONSOLE:** Adds unnecessary build-step complexity. |
| **Svelte 5** | Small ($120\text{ KB}$) | Maximum | Moderate | Supported | **EVALUATED FOR FUTURE MAJOR SUITE:** If complex multi-window state is needed. |
