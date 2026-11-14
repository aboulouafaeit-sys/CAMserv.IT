# CAMserv QA & Chaos Engineering Test Plan
**Document ID:** QA-CHAOS-2026-001  
**Author:** Principal QA Architect & Chaos Engineering Lead  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Testing Scope:** Extended Soak Testing, Adversarial Fuzzing, and Systematic Fault Injection

---

## 1. Quality Assurance Hierarchy & Test Suites

CAMserv maintains a comprehensive, multi-tiered automated testing hierarchy:

| Test Layer | Directory Location | Focus & Verification | Current Count | Target Pass Criteria |
|---|---|---|---|---|
| **Unit Tests** | `tests/unit/` | Pure function correctness, Kalman equations, encryption | 64 | 100% Pass in $< 2.0\text{s}$ |
| **Integration Tests** | `tests/integration/` | Ingestion-to-inference pipeline, SQLite WAL, WebSockets | 42 | 100% Pass in $< 5.0\text{s}$ |
| **Adversarial Tests** | `tests/adversarial/` | Zero-sized frames, corrupted NALs, token forgery | 18 | 100% Pass (Zero crashes) |
| **Scenario Tests** | `tests/scenarios/` | End-to-end incident triggers, pre-roll vault sealing | 12 | 100% Pass (Verified `.vault`) |
| **Soak & Stress Tests** | `tests/chaos/` | 24h/72h continuous load, memory leak regression | Ongoing | Zero leak ($< 1\text{ MB/hr}$) |

---

## 2. Extended Soak & Stability Testing Protocols

Surveillance servers run continuously for months without maintenance. To eliminate slow memory leaks, handle exhaustion, and file descriptor starvation:

1. **24-Hour Continuous Multi-Stream Soak:**
   - 8 synthetic 1080p @ 30 FPS streams ingested continuously.
   - Inference running at full rate with simulated crowd movement.
   - *Pass Condition:* RSS RAM growth $< 50\text{ MB}$ over 24 hours; zero dropped frames on vault recording.
2. **72-Hour Weekend Endurance Soak:**
   - Simulates alternating day/night cycles with automatic software ISP CLAHE toggling.
   - *Pass Condition:* Process handle count and thread count remain constant $\pm 2\%$.
3. **7-Day Enterprise Stress Test:**
   - 16 concurrent RTSP streams on Tier 3 hardware with periodic simulated high-threat incidents ($100$ alerts/day).
   - *Pass Condition:* All generated `.vault` evidence packages verify cryptographically without corruption.

---

## 3. Chaos Engineering & Fault Injection Matrix

| Injected Fault | Injection Mechanism | Expected System Response | Verification Metric |
|---|---|---|---|
| **Decoder SIGKILL** | `kill -9` on video ingestion worker process. | Subprocess watchdog detects termination; respawns decoder in $< 500\text{ms}$. | Stream resumes; audit log records restart event. |
| **Network Blackhole** | `iptables -A INPUT -p tcp --dport 554 -j DROP` on camera IP. | Exponential backoff circuit breaker activates; API and sibling streams unaffected. | Zero crash; reconnection succeeds when rule is flushed. |
| **VRAM Thrashing** | Synthetic PyTorch allocation saturating 99% of GPU memory. | Inference worker detects OOM; drops tensor resolution to $480 \times 480$; migrates to CPU if needed. | Platform remains responsive; zero unhandled exception. |
| **Disk Write Choke** | Throttling vault I/O to $100\text{ KB/s}$ using `cgroups` / `blkiotune`. | 15s RAM ring buffer absorbs burst; drops routine video; preserves incident pre-roll. | Incident package sealed successfully without buffer overflow. |
| **RTSP NAL Fuzzing** | Corrupting random bits in H.264 SPS/PPS parameters. | Frame decoder catches `DecodingError`; drops corrupted slice; requests IDR keyframe. | Zero segmentation fault; video recovers on next keyframe. |
