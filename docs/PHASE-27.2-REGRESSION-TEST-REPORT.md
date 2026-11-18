# CAMserv Phase 27.2 — Regression Test Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Regression Safety & Software Assurance  
**Architecture:** Single Organization / Local-First Deployment  
**Execution Environment:** Windows 11 Enterprise x86_64, Python 3.14.8, pytest 9.2.0  
**Test Run Timestamp:** 2026-11-18T18:21:18+01:00  

---

## 1. Executive Summary

Phase 27.2 executed the complete CAMserv automated test suite to confirm that new capabilities (process isolation, model registry integrity verification, real pixel OCR, homography speed calibration) introduced **zero software regressions** across existing platform modules, storage engines, identity controls, and recording pipelines.

---

## 2. Test Execution Summary

- **Total Test Files:** 90 test files.
- **Total Test Cases Collected:** 669 tests.
- **Total Tests Passed:** 669 tests.
- **Total Tests Failed:** 0 tests.
- **Total Tests Skipped:** 0 tests.
- **Overall Pass Rate:** **100.0%**.
- **Total Suite Execution Time:** ~118.4 seconds.

---

## 3. Subsystem Test Breakdown

| Subsystem / Area | Test Files | Tests | Passed | Regressions | Status |
|---|---|---|---|---|---|
| Platform Stability & Bounded Queues | 4 | 71 | 71 | 0 | **PASS** |
| Identity & Access Security (Phase 26.x) | 4 | 90 | 90 | 0 | **PASS** |
| Visual Intelligence Platform (Phase 27 & 27.1) | 8 | 40 | 40 | 0 | **PASS** |
| Phase 27.2 Real AI & Process Isolation | 1 | 14 | 14 | 0 | **PASS** |
| NVR Storage, Recording Engine & Hashing | 8 | 34 | 34 | 0 | **PASS** |
| Forensics & Tamper-Evident Evidence Vault | 4 | 22 | 22 | 0 | **PASS** |
| Hardware Appliances & Tier Management | 6 | 35 | 35 | 0 | **PASS** |
| Operator Workspace & UI Presentation | 3 | 42 | 42 | 0 | **PASS** |
| Adversarial, Ingestion & Stream Isolation | 12 | 86 | 86 | 0 | **PASS** |
| Historical & Pre-LTS Qualification Suites | 40 | 235 | 235 | 0 | **PASS** |
| **Total** | **90** | **669** | **669** | **0** | **100.0% PASS** |

---

## 4. Invariant Protection Verification

- **Audit Ledger Invariant:** `logs/audit.jsonl` size verified at exactly 20,977 bytes, SHA-256 `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525` untouched.
- **Official Brand Assets:** 24 branding and visual identity assets verified intact.
- **Hyperlink & Image Integrity:** `scripts/verify_links_and_images.py` confirmed 100% valid references.
- **Git State:** 0 commits, 0 pushes, 0 tags, 0 merges executed. All work preserved locally.
