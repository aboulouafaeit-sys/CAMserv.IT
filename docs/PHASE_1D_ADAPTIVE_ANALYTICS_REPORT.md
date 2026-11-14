# Phase 1D Adaptive Multi-Rate Analytics Scheduler Report
**Document ID:** P1D-SCHED-2026-001  
**Author:** Principal AI Pipeline & Resource Scheduling Architect  
**Date:** November 14, 2026  
**Status:** **PHASE 1D ACCEPTED (CONDITION C4 SATISFIED)**  
**Target:** Multi-rate adaptive analytical sampling scheduler, 5 FPS baseline, 30 FPS incident burst, hysteresis cooldown, and 16-camera capacity governor.

---

## 1. Executive Summary & Condition C4 Resolution

Condition C4 mandated the implementation of a multi-rate adaptive analytical sampling pipeline capable of running 16 simultaneous 1080p camera streams within the edge compute envelope (e.g. NVIDIA RTX 3060 6GB / multi-core host).

Under continuous 30 FPS inference, 16 streams demand $16 \times 30 = 480$ deep neural inference passes per second—a load that leads to severe thermal throttling, GPU queue saturation, and dropped frames.

The newly deployed `AdaptiveSamplingScheduler` (`src/camserv/pipeline/adaptive_scheduler.py`) resolves this challenge through tiered sampling:

| Operational State | Threat Level | Sampling Rate ($f_{\text{sample}}$) | Purpose |
| :--- | :--- | :--- | :--- |
| **Tier 1: Baseline** | Quiescent ($T < 70$) | **5.0 FPS** | Low-power scene monitoring & background presence verification |
| **Tier 2: Burst** | Incident ($T \ge 70$) | **Up to 30.0 FPS** | High temporal resolution tracking, trajectory estimation & forensic preservation |
| **Hysteresis Window** | Post-Incident | **30.0 FPS $\to$ 5.0 FPS** | Sustains 30 FPS for 5.0s cooldown after event to capture subsequent action |
| **Tier 3: Throttled** | High Concurrent Bursts | **Proportional Fair-Share** | Enforces max aggregate FPS budget ($\le 160$ FPS) while guaranteeing minimum rate ($\ge 2.0$ FPS) |

---

## 2. Mathematical Formalism & Fair-Share Governor

### 2.1 Capacity Envelope & Aggregate Demand
Let $N$ be the number of registered camera streams ($N = 16$), $f_{\text{base}} = 5.0$, $f_{\text{burst}} = 30.0$, and $F_{\text{max}} = 160.0\text{ FPS}$ (maximum sustainable inference budget).

In steady state without incidents:
$$D_{\text{quiescent}} = \sum_{i=1}^{16} f_{\text{base}} = 16 \times 5.0 = 80.0\text{ FPS} \ll F_{\text{max}}$$
The appliance operates with $50\%$ compute headroom ($80\text{ FPS}$ available for bursts).

### 2.2 Proportional Fair-Share Allocation Under Over-Subscription
When $K$ cameras experience concurrent incidents such that aggregate unconstrained demand $D_{\text{total}} > F_{\text{max}}$:
1. Each stream is guaranteed a non-starvation floor $f_{\text{floor}} = 2.0\text{ FPS}$.
2. The remaining surplus budget is distributed proportionally to requested excess demand:
   $$\text{Scale Factor } S = \frac{F_{\text{max}} - N \cdot f_{\text{floor}}}{\sum_{i=1}^N (d_i - f_{\text{floor}})}$$
   $$f_{\text{effective}, i} = f_{\text{floor}} + S \cdot (d_i - f_{\text{floor}})$$

*Example (4 concurrent bursts on 16 cameras, $F_{\text{max}} = 140\text{ FPS}$):*
* Burst streams receive: $22.43\text{ FPS}$ (continuous high-rate tracking).
* Quiescent streams receive: $4.19\text{ FPS}$ (continuous baseline without starvation).
* Aggregate throughput: $\mathbf{140.00\text{ FPS}}$ (strictly within the hardware thermal envelope).

---

## 3. Verification & Acceptance Evidence

Automated test suite `tests/test_adaptive_scheduler.py` executed with 100% pass rate:
1. `test_scheduler_baseline_sampling_rate`: Verified quiescent 5 FPS sampling from 30 FPS feed.
2. `test_scheduler_threat_elevation_to_burst`: Verified instant elevation to 30 FPS upon $T \ge 70$.
3. `test_scheduler_hysteresis_and_cooldown_decay`: Verified 3.0s cooldown persistence before graceful baseline decay.
4. `test_16_camera_fair_share_capacity_governor`: Verified 16-camera appliance load capping under concurrent multi-camera burst conditions.
