# CAMserv Known Limitations & Operational Boundaries

**Document ID:** LIMITATIONS-2026-001  
**Classification:** Operational Transparency Disclosure  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Scope and Purpose

In accordance with CAMserv's engineering honesty rules, this document explicitly details all known limitations, unsupported configurations, physical hardware prerequisites, and operational boundaries of the software.

---

## 2. Hardware and Environment Boundaries

1. **Bare-Metal vs. Emulated Validation:**
   - Automated tests run against software emulators and synthetic RTSP video generators in CI.
   - Physical bare-metal certification across specific hardware acceleration ASICs (NVIDIA Jetson, Intel Arc, Hailo-8) requires physical hardware access.
2. **Virtualization Network Limitations:**
   - In cloud or virtualized container environments (e.g., Docker bridge networks, AWS EC2), UDP multicast discovery (ONVIF WS-Discovery on `239.255.255.250:3702`) is typically blocked by host hypervisors. In such environments, manual RTSP camera registration is mandatory.
3. **GPU Memory Footprint:**
   - High-resolution multi-stream inference (e.g., eight simultaneous 4K streams at 30 FPS) requires discrete GPUs with at least 8GB to 16GB of dedicated VRAM. On memory-constrained devices, dynamic resolution decimation is automatically engaged.

---

## 3. Algorithmic and Computer Vision Boundaries

1. **Non-Biometric Constraint:**
   - CAMserv does not perform facial recognition, iris scanning, or biometric identification. It cannot and will not tell operators "who" a person is.
2. **Epistemic Uncertainty:**
   - AI outputs are probabilistic hypotheses. Occlusions, severe weather (heavy fog, blizzards), or dirty lenses can degrade detection accuracy.
3. **Tripwire Accuracy:**
   - Line-crossing detection accuracy depends on accurate ground-contact plane estimation. Steep overhead camera angles provide superior line-crossing accuracy compared to low-angle grazing views.
4. **No Universal Camera Compatibility:**
   - Certain low-cost consumer IP cameras utilize proprietary cloud-only protocols (e.g., Tuya, Ring, Nest) that intentionally omit standard RTSP/ONVIF streams. CAMserv does not support proprietary cloud-locked protocols.

---

## 4. Legal & Compliance Disclosures

1. **Dual-Control Export Responsibility:**
   - The platform strictly enforces dual-control multi-signature authorization before exporting raw unmasked footage. Organizations must designate separate users for `FORENSIC_EXPERT` and `DPO` roles.
2. **Local Video Surveillance Laws:**
   - Users are responsible for complying with municipal, national, and international laws regarding public video recording, privacy notices, and labor union notifications.
