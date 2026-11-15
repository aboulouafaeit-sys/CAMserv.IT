# CAMserv — Phase 3 Professional Operator Experience & Workflow Governance

**Document ID:** ARCH-OPERATOR-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Stage 8 Deliverable  
**Date:** November 15, 2026  
**Status:** PRODUCTION OPERATOR EXPERIENCE & UI BLUEPRINT  
**Author / Authority:** Product Design Director, UI/UX Systems Lead & Chief Software Architect  

---

## 1. Executive Summary & Design Philosophy

The **CAMserv Operator Experience** establishes a mission-critical, high-assurance security operations interface for enterprise monitoring centers, municipal control rooms, and industrial security posts.

Surveillance operators must maintain cognitive awareness across dozens of simultaneous camera streams without sensory overload, triage complex behavioral incidents under high-stress conditions, and inspect forensic evidence with mathematical certainty.

### Core Human-Centered Engineering Invariants:
1. **Sub-50ms Latency & Zero External CDN Dependencies:** The interface is 100% self-hosted on the appliance. Assets, fonts, and scripts are served locally without external CDN requests, guaranteeing air-gapped sovereignty.
2. **Mandatory Human-in-the-Loop (HITL) Action Gating:** Algorithmic inferences are probabilistic hypotheses (`is_prediction = True`). **No physical consequential action (locking gates, dispatching guards, triggering sirens) may be dispatched without explicit human operator confirmation.**
3. **Fail-Closed Visual Obscuration:** Operator live walls display derivative privacy-masked frames by default. Live streams automatically transition to full blackout if detection fails.
4. **Unified Design System Across 14 Screens:** A cohesive visual identity combining high-contrast typography ($> 4.5:1$), subtle glassmorphism, and clear hierarchical color tokens.

---

## 2. The 14 Professional Operations Console Screens

```
+─────────────────────────────────────────────────────────────────────────────────+
|                       CAMserv ENTERPRISE 14-SCREEN SUITE                        |
+─────────────────────────────────────────────────────────────────────────────────+
| 01. Security Operations Dashboard | Fleet health, incident velocity, alarm queue|
| 02. Live Camera Wall              | Dynamic multi-stream matrix with fail-closed|
| 03. Camera Management             | RTSP/ONVIF discovery, resolution, FPS       |
| 04. Device Management             | Physical appliances, hardware tier, telemetry|
| 05. AI Intelligence Monitor       | 17-keypoint skeletal stick figures, vectors |
| 06. Event Investigation           | Timeline scrubber, reasoning traces, notes  |
| 07. Evidence Explorer             | Dual-hash manifest verification, side-by-side|
| 08. Privacy Configuration         | Obscuration zones, fail-closed policy toggle|
| 09. Storage Management            | 48h rolling retention, judicial hold locks  |
| 10. Hardware Diagnostics          | Die temperatures, VRAM, provider hierarchy  |
| 11. System Health                 | Service supervisor status, memory drift     |
| 12. User & Permission Management  | RBAC matrices, session controls, MFA tokens |
| 13. Central Multi-Site Management | Geographic fleet topology, site isolation   |
| 14. Software Update Management    | Signed OTA staged rollout, A/B rollback slot|
+─────────────────────────────────────────────────────────────────────────────────+
```

---

## 3. Human-in-the-Loop Operational Workflow

Implemented in `src/camserv/web/operator_workflow.py`:

```
+-------------------+
| 1. AI DETECTION   |  Probabilistic hypothesis flagged (e.g., Perimeter Dwell, p = 0.94)
+---------┬---------+
          ▼
+-------------------+
| 2. QUEUED REVIEW  |  High-severity alert appears on operator triage queue
+---------┬---------+
          ▼
+-------------------+
| 3. INSPECTION     |  Operator opens Event Explorer, reviews pose telemetry & derivatives
+---------┬---------+
          ▼
+-------------------+
| 4. HUMAN DECISION |  Human operator accepts or rejects alert
+---------┬---------+
          ├────────────────────────────────┬───────────────────────────────┐
          ▼ (Operator Confirms Threat)     ▼ (Authorized Night Cleaner)    ▼
+-------------------+             +-------------------+
| 5. CONFIRMED      |             | DISMISSED FALSE   |  Feedback recorded to calibrate
+---------┬---------+             | POSITIVE          |  model detection thresholds
          ▼                       +---------┬---------+
+-------------------+                       │
| 6. DISPATCH       |  Operator explicitly  │
|    AUTHORIZATION  |  approves physical    │
+---------┬---------+  response             │
          │                                 │
          └────────────────┬────────────────┘
                           ▼
                  +-------------------+
                  | 7. SEAL IN AUDIT  |  Case permanently sealed in SHA-256 Merkle chain
                  +-------------------+
```

### Invariant Enforcement:
If an API or automated script calls `authorize_consequential_dispatch` on an event in `QUEUED_FOR_REVIEW`, `UNDER_INSPECTION`, or `DISMISSED_FALSE_POSITIVE`, the engine raises `WorkflowActionError`, halting execution.

---

## 4. Stage 8 Acceptance Decision

$$\mathbf{STAGE\_8\_ACCEPTANCE\_VERDICT: \quad ACCEPTED}$$

All deliverables for Stage 8 (Professional Operator Experience & Workflow Governance) are implemented, verified by 4 unit tests in `tests/test_operator_workflow.py`, and documented.
