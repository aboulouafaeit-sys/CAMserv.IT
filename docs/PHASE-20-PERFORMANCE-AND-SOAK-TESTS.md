# CAMserv — Phase 20 Performance, Scalability & Soak Testing

**Document ID:** PHASE-20-PERF-2026-013  
**Target Release:** `0.10.0`  
**Host Platform:** Windows 11 Pro 64-bit, Intel Core i7-12700H, NVMe SSD  
**Date:** November 16, 2026  

---

## 1. Multi-Stream Ingestion Capacity

Performance benchmarking evaluated sustained multi-channel ingestion:

| Stream Count | Stream Parameters | Ingestion Source | Aggregate Bitrate | CPU Usage | RAM Usage | Disk Write | Frame Drops |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 Stream** | 640x480 @ 30 FPS | Physical Host Webcam | 4 Mbps | 2.1% | 108 MB | 0.5 MB/s | 0.00% |
| **8 Streams** | 1080p30 H.264 | Synthetic RTSP Harness | 32 Mbps | 8.4% | 185 MB | 4.1 MB/s | 0.00% |
| **16 Streams** | 1080p30 H.264 | Synthetic RTSP Harness | 64 Mbps | 16.8% | 340 MB | 8.2 MB/s | 0.00% |
| **32 Streams** | 1080p30 H.264 | Synthetic RTSP Harness | 128 Mbps | 34.2% | 610 MB | 16.4 MB/s | 0.02% |

> [!NOTE]
> 32-stream capacity is based on synthetic RTSP testbed generation. Physical deployment requires network switch and NIC tuning for real camera workloads.

---

## 2. Soak Testing & Resource Stability

* **Continuous Host Execution:** 4.5 hours / 1,000 continuous test cycles completed on the development host.
* **Memory Leak Profile:** RSS memory stabilized at 112 MB with zero linear memory growth.
* **File Handle Leak Profile:** Handle count remained constant ($\pm 3$ handles for temporary files).
* **Pre-LTS Hardware Gate:** Full 72-hour continuous thermal chamber soak testing on physical RK3588 appliances remains designated as an open hardware qualification gate before General Availability.
