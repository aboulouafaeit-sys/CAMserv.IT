# CAMserv Shared Task Registry
**Master Tracking Board for Multi-Agent Engineering & Product Delivery**

| Task ID | Phase | Owner | Scope / Deliverable | Status | Dependencies | Verification Criteria |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TSK-GOV-01** | Phase A | Chief Architect | Baseline repository audit report | **DONE** | None | Verified 56 files, 95/95 tests |
| **TSK-GOV-02** | Phase B | Chief Architect | Governance setup (ADR 001-006, Registry, Risks, Changelog) | **IN_PROGRESS** | TSK-GOV-01 | Complete markdown governance tree |
| **TSK-ENG-01** | Phase C | Video Pipeline | CLI entrypoint `src/camserv/main.py` (`camserv serve`, etc.) | **PLANNED** | TSK-GOV-02 | `python -m camserv.main --help` passes |
| **TSK-ENG-02** | Phase C | NVR/Camera Eng | ONVIF Discovery, Profile S/T client, and NVR tester framework | **PLANNED** | TSK-GOV-02 | Tested with simulated ONVIF cameras |
| **TSK-ENG-03** | Phase C | Event Intel Eng | Temporal event graph engine with observation tracing | **PLANNED** | TSK-GOV-02 | Event schemas carry supporting observations & versions |
| **TSK-ENG-04** | Phase C | Forensics Eng | Asymmetric Ed25519 signatures & standalone evidence verification CLI | **PLANNED** | TSK-GOV-02 | CLI verifies tamper detection & signatures |
| **TSK-ENG-05** | Phase C | Database Eng | SQLite metadata repository for cameras, users, and audit records | **PLANNED** | TSK-GOV-02 | State survives service restarts |
| **TSK-ENG-06** | Phase C | Platform Eng | Hardware detection (`src/camserv/platform/hardware.py`) & deployment matrix | **PLANNED** | TSK-GOV-02 | Auto-detects CPU/CUDA/VRAM/OS capabilities |
| **TSK-DSN-01** | Phase D | Creative Director | CAMserv brand identity, logo, typography, color system & SVGs | **PLANNED** | TSK-GOV-02 | Original vector SVGs (primary, symbol, monochrome) |
| **TSK-DSN-02** | Phase D | UI/UX Designer | 12 Product screen specifications & information architecture | **PLANNED** | TSK-DSN-01 | Documented workflows, states, and layouts |
| **TSK-DSN-03** | Phase E | Frontend Eng | CAMserv Enterprise Web Console (12 live screens, design tokens, REST integration) | **PLANNED** | TSK-DSN-02, TSK-ENG-01 | UI served directly by FastAPI application |
| **TSK-QA-01** | Phase F | QA Engineer | Independent test expansion, ONVIF tests, forensics tests, UI route tests | **PLANNED** | TSK-ENG-01..06, TSK-DSN-03 | 100% test pass rate with expanded suite |
| **TSK-REL-01** | Phase H | Chief Architect | Final release candidate validation, documentation sign-off | **PLANNED** | All | Zero regressions, complete documentation |
