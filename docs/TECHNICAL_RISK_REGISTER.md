# CAMserv Technical Risk Register & Mitigation Strategy
**Document ID:** RISK-REG-2026-001  
**Author:** Principal Risk Architect & Systems Engineering Director  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Review Cadence:** Bi-Weekly Engineering Architectural Review

---

## 1. Risk Evaluation Matrix

Risks are quantified on a standard $4 \times 4$ probability and impact matrix:
* **Probability:** Low ($< 10\%$), Medium ($10\% - 40\%$), High ($40\% - 75\%$), Critical ($> 75\%$).
* **Impact:** Low (Minor degradation), Medium (Service degradation), High (Service disruption / data loss), Critical (Platform failure / legal liability).

---

## 2. Comprehensive Risk Register

| Risk ID | Risk Description & Root Cause | Prob. | Impact | Pre-Sev | Architectural Mitigation Strategy | Post-Sev | Owner |
|---|---|---|---|---|---|---|---|
| **RSK-GIL-01** | **Python GIL Bottleneck:** Under multi-camera 4K/1080p load, Python Global Interpreter Lock saturates CPU, causing frame drops and latency spikes. | **HIGH** | **HIGH** | **CRITICAL** | Migrate camera ingestion and decoding to dedicated OS subprocesses communicating via POSIX shared memory ring buffers (`/dev/shm`). | **LOW** | Video Pipeline Lead |
| **RSK-UDP-02** | **OpenCV RTSP Packet Drop:** `cv2.VideoCapture` defaults to UDP; network jitter causes frame tearing and decoding corruption. | **HIGH** | **HIGH** | **CRITICAL** | Enforce TCP transport via supervised FFmpeg subprocesses (`-rtsp_transport tcp`) with hardware NVDEC decoding. | **LOW** | Video Systems Eng |
| **RSK-WRM-03** | **Storage Root Tampering:** Compromised host root access deletes or alters evidence files on disk, invalidating legal chain of custody. | **LOW** | **CRITICAL** | **HIGH** | Enforce OS-level immutable WORM file attributes (`chattr +i` on Linux) and anchor signing keys in hardware TPM 2.0. | **LOW** | Forensic Architect |
| **RSK-ALM-04** | **AI False Alarm Fatigue:** Model overconfidence on night shadows or insect movement causes operator alert fatigue and ignored alarms. | **HIGH** | **MEDIUM** | **HIGH** | Implement Platt temperature scaling, 95% epistemic confidence bounds, and multi-frame temporal persistence state machine. | **LOW** | AI Lead |
| **RSK-OOM-05** | **GPU VRAM Exhaustion:** Complex multi-stream segmentation causes CUDA Out-of-Memory crashes during sudden crowd surges. | **MEDIUM** | **HIGH** | **HIGH** | Adaptive resource watchdog: dynamically downsizes inference tensors from $640 \times 640$ to $480 \times 480$ and migrates to CPU if needed. | **LOW** | Hardware Lead |
| **RSK-PRV-06** | **Unredacted Identity Leak:** Model segmentation failure leaks unmasked human faces in public or exported surveillance footage. | **LOW** | **CRITICAL** | **HIGH** | Fail-Closed Redaction: if analytical confidence $< 0.40$, the entire frame is obscured with a neutral solid mask before display/export. | **LOW** | Privacy Architect |
| **RSK-SQL-07** | **SQLite Database Locking:** High-velocity alert bursts during physical incidents trigger SQLite database lock errors. | **MEDIUM** | **MEDIUM** | **MEDIUM** | Enforce Write-Ahead Logging (WAL) mode, 5000ms busy timeout, and an in-memory 10,000-item FIFO spillover queue. | **LOW** | Database Architect |
| **RSK-MEM-08** | **Slow Memory Leak:** Long-running OpenCV or Python object references cause gradual memory bloat over weeks of uptime. | **MEDIUM** | **HIGH** | **HIGH** | Periodic worker process recycling (respawn ingestion worker every 24 hours), automated memory thresholds, and 72-hour soak testing. | **LOW** | SRE / DevOps Lead |
| **RSK-SUP-09** | **Upstream Dependency Compromise:** Malicious package update in PyPI supply chain compromises platform security. | **LOW** | **CRITICAL** | **HIGH** | Hermetic builds with strict SHA-256 hash pinning (`requirements.lock`), automated `pip-audit` CI gates, and Cosign container signing. | **LOW** | DevSecOps Lead |
| **RSK-RTL-10** | **Arabic UI Directionality Glitches:** Text alignment and HUD telemetry cards break in pure Arabic RTL mode. | **LOW** | **LOW** | **LOW** | Standardized CSS logical properties (`margin-inline-start`, `text-align: start`) and dedicated RTL visual regression tests. | **LOW** | Frontend Lead |
