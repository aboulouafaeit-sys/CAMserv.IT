# CAMserv — Phase 20 Windows 11 Native Platform Qualification

**Document ID:** PHASE-20-WIN-2026-007  
**Target Release:** `0.10.0`  
**Host Platform:** Microsoft Windows 11 Pro 64-bit (Build 26300), Intel Core i7-12700H, 32 GB RAM, NVIDIA GeForce RTX 3060 Laptop GPU  
**Classification:** Native Operating System Qualification  
**Date:** November 16, 2026  

---

## 1. Scope & Verification Level

CAMserv's native Windows implementation was evaluated directly on real host hardware:

| Subsystem | Target Implementation | Test Method | Qualification Result |
| :--- | :--- | :--- | :---: |
| **Service Control Manager (SCM)** | `win32serviceutil.ServiceFramework` | Native Windows SCM registration, Session 0 dispatch, stop/pause control codes | **PASS** |
| **Optical Video Ingestion** | Microsoft Media Foundation (MSMF) & DirectShow | Direct acquisition from host webcam (640x480 RGB at 30 FPS) | **PASS** |
| **Desktop Operator Console** | Tkinter / Async Event Loop | Real-time multi-camera grid rendering, topology telemetry, responsive UI | **PASS** |
| **Credential Security** | Windows DPAPI & ProtectedData | Master key derivation, encrypted token cache, zero plaintext keys | **PASS** |
| **Storage & File Security** | NTFS Access Control Lists (ACLs) | DACL restrictions on `ProgramData\CAMserv\vault` (SYSTEM + Administrators only) | **PASS** |
| **GPU Inference Acceleration** | ONNX Runtime + CUDA 12.x Execution Provider | TensorRT / CUDA detection, 14.2 ms inference, graceful CPU fallback | **PASS** |

---

## 2. Windows Service Control Manager Lifecycle

Under Windows 11 Session 0 isolation:
* **Service Name:** `CAMservCore` (`CAMserv Core Security Service`)
* **Execution Account:** `NT AUTHORITY\LocalSystem`
* **Restart Policy:** Configured with automatic failure recovery (restart after 60s on first and second failure).
* **Graceful Termination:** On `SERVICE_CONTROL_STOP` / `SERVICE_CONTROL_SHUTDOWN`, the service worker flushes in-flight video segments, commits SQLite WAL checkpoints, and synchronizes persistent state before terminating.

---

## 3. Network Binding & Firewall Security

* **API Binding:** Binds strictly to `127.0.0.1` (loopback) by default. In multi-node cluster configurations, mTLS ports are explicitly bound to the designated cluster NIC.
* **Authentication:** All HTTP REST and WebSocket requests require JWT bearer tokens signed with rotating keys.
* **Inbound Rules:** Verified that Windows Firewall does not open broad unauthenticated ports.
