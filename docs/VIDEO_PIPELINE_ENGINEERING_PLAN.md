# CAMserv Video Pipeline & Hardware Decoding Engineering Plan
**Document ID:** VID-PLAN-2026-001  
**Author:** Principal Video Systems Engineer & Streaming Architect  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Target Video Latency:** $< 120\text{ ms}$ Glass-to-Glass

---

## 1. Video Subsystem Modernization

The current reliance on standard OpenCV `cv2.VideoCapture` is replaced by an enterprise-grade, process-isolated streaming engine built on supervised **FFmpeg / GStreamer subprocesses** with hardware hardware-accelerated decode surfaces.

### 1.1 Ingestion Architecture Comparison
| Capability | Current OpenCV Implementation | Target Supervised FFmpeg Subprocess |
|---|---|---|
| **Process Isolation** | Single-threaded in Python event loop (GIL bottleneck) | Dedicated OS Subprocess per camera (Crash-Isolated) |
| **Transport Control** | Defaults to UDP with packet drop | Strict TCP interleaved (`-rtsp_transport tcp`) |
| **Hardware Decoding** | Requires OpenCV build with CUDA | Native NVDEC (`-hwaccel cuda -c:v h264_cuvid`) / VAAPI |
| **Inter-Process Transfer** | Pickled numpy arrays in memory | Zero-Copy POSIX Shared Memory (`/dev/shm`) |
| **Buffering Strategy** | Opaque internal OS socket buffer | Ring buffer with strict drop-oldest backpressure |
| **Latency Budget** | $280\text{ ms} - 450\text{ ms}$ | $85\text{ ms} - 120\text{ ms}$ |

---

## 2. Zero-Copy Shared Memory Frame Distribution

```
+------------------+         +------------------+         +------------------+
| Camera Worker 1  |         | Camera Worker 2  |         | Camera Worker N  |
| (FFmpeg / NVDEC) |         | (FFmpeg / NVDEC) |         | (FFmpeg / NVDEC) |
+--------+---------+         +--------+---------+         +--------+---------+
         |                            |                            |
         v                            v                            v
+----------------------------------------------------------------------------+
|                POSIX Shared Memory Ring Buffer (/dev/shm/camserv_pool)     |
|   - 120 Pre-Allocated 1080p Surfaces (YUV420p / BGR24)                     |
|   - Lock-Free Circular Header Ring with Monotonic Sequence Counters         |
+----------------------------------------------------------------------------+
         |                            |                            |
         v                            v                            v
+------------------+         +------------------+         +------------------+
| GPU Inference    |         | 15s RAM Vault    |         | WebRTC Streamer  |
| Worker (TensorRT)|         | Pre-Roll Buffer  |         | (Live Operators) |
+------------------+         +------------------+         +------------------+
```

### 2.1 Shared Memory Ring Buffer Mechanics
* **Buffer Layout:** Fixed-size memory block pre-allocated at boot. Each frame slot contains:
  - Header (64 bytes): Frame ID, monotonic timestamp, resolution, format, sequence counter.
  - Payload: Raw byte surface ($1920 \times 1080 \times 3 \text{ bytes} \approx 6.22\text{ MB}$).
* **Lock-Free Semantics:** Atomic compare-and-swap pointer arithmetic ensures inference workers read the latest available frame without blocking ingest subprocesses.

---

## 3. Autonomous Software ISP & Dynamic CLAHE Equalization

Surveillance cameras in physical infrastructure frequently suffer from adverse lighting (night darkness, blinding sun glare, backlighting).
* **LAB CLAHE Pipeline:** Converts frame to CIE L\*a\*b\* color space; applies Contrast Limited Adaptive Histogram Equalization exclusively to the $L$ (luminance) channel with clip limit $2.5$ and tile grid size $8 \times 8$.
* **5-Second Stream Fingerprinting:** Every stream is dynamically classified:
  - `PROFILE_STANDARD`: Clean daylight ($L_{mean} \in [80, 180]$). CLAHE bypassed to save GPU cycles.
  - `PROFILE_LOW_LIGHT`: Underexposed night scene ($L_{mean} < 50$). Real-time CLAHE activated.
  - `PROFILE_NOISY`: High sensor gain / thermal noise ($L_{variance} > 800$). Bilateral filtering applied to object ROIs.
