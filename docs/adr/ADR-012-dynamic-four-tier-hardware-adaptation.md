# ADR-012: Dynamic 4-Tier Hardware Adaptation & Load Shedding Feedback Loops
**Status:** ACCEPTED  
**Date:** 2026-11-14  
**Context:** Deploying fixed-compute surveillance software across diverse client hardware (ranging from low-cost edge IPCs to enterprise multi-GPU clusters) leads to frequent crashes or underutilized hardware.  
**Decision:** Implement boot-time hardware probing that maps host resources into one of 4 defined operational profiles (`TIER_1_EDGE` to `TIER_4_ENTERPRISE`) coupled with a real-time pressure shedding watchdog.  
**Consequences:** Universal hardware portability; under heavy CPU/GPU load, analytics gracefully degrade in 3 stages (drop sample rate, downscale tensor, emergency capture-only) without terminating video recording or corrupting vaults.
