# CAMserv — Phase 22 Visual Experience & UI/UX Baseline

**Document ID:** PHASE-22-BASELINE-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** 22 — Premium Visual Experience Overhaul, Advanced Glassmorphism UI/UX & Enterprise Design Engineering  
**Starting Git Baseline:** `1cecf14fd4995c4bfe0add540c7307d38ae428e1` (Branch: `main`)  
**Design Direction:** Cinematic Dark / Multi-Layer Glassmorphism / Advanced Visual Effects  
**Brand Identity Invariant:** Official CAMserv Logo Preserved Exactly  
**Date:** November 17, 2026  
**Auditor:** Principal Product Designer, Senior Desktop Architect & Independent Quality Auditor  

---

## 1. Executive Purpose & Scope

Phase 22 executes a comprehensive, production-oriented visual and user-experience overhaul of CAMserv. This transformation upgrades the platform from a utilitarian dark dashboard into a world-class, commercial-grade security intelligence control room interface.

The visual overhaul spans:
1. **The Web Command & Control Console** (`src/camserv/web/`): Full Cinematic Dark Glassmorphism, multi-layer elevation system, responsive viewport scaling, and refined operational interactions.
2. **The Desktop Operator Console** (`src/camserv/desktop/console.py`): Native Windows 11 & cross-platform desktop UI styled to harmonize with the cinematic design tokens.
3. **Inference & Forensic Overlays** (`src/camserv/inference/hud_renderer.py`): Cinematic tactical HUD styling, spatial redaction indicators, and probabilistic telemetry.

---

## 2. Invariant Baselines & Non-Negotiable Rules

### 2.1 Audit Log Baseline (Rule 1)
* **File:** `logs/audit.jsonl`
* **Byte Count:** Exactly **20,977 bytes**
* **SHA-256 Digest:** `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`
* **Status:** Verified inviolate before Phase 22 activities.

### 2.2 Official Brand Asset Inventory (Rule 2.1)
The official CAMserv logo assets are cataloged, verified, and locked against modification:

| Asset Name | Canonical Path | Format / Dimensions | SHA-256 Digest (First 16 chars) | Role / Usage |
| :--- | :--- | :---: | :---: | :--- |
| **Master Dark Logo** | `assets/branding/camserv-logo-transparent.png` | 683x757 PNG | `b75ded3078026662` | Primary header logo on dark glass |
| **Master Light Logo** | `assets/branding/camserv-logo-light-background.png` | 1024x1024 PNG | `2beed217b9724d06` | Secondary light-mode logo |
| **Brand Symbol** | `assets/branding/camserv-symbol.png` | 636x643 PNG | `6e38510ec4357349` | Compact square icon / avatar |
| **Wordmark Vector** | `assets/branding/camserv-wordmark.svg` | Vector SVG | `ad6d86cc04647689` | Precision typographic branding |
| **Horizontal Logo** | `assets/branding/camserv-logo-horizontal.svg` | Vector SVG | `d6251ad5d3ca39df` | Horizontal banner presentations |
| **Emblem Vector** | `assets/branding/camserv-emblem.svg` | Vector SVG | `bafce9c17889be15` | Security crest / seal icon |
| **Desktop App Icon** | `assets/branding/camserv-app-icon.png` | 512x512 PNG | `86bc99fef1da32aa` | Windows taskbar & installer icon |

All redrawing, AI regeneration, geometric distortion, or palette shifts of these assets are strictly prohibited.

### 2.3 Functional & Security Invariants (Rule 2.2 & 2.3)
* **Fail-Closed Privacy:** Video feeds maintain automatic blackout if the detection pipeline is unconfigured or encounters faults. The UI cannot bypass privacy redaction without verified judicial dual-control quorum.
* **Telemetry Truthfulness:** The UI explicitly distinguishes between `actual` (hardware-probed), `simulated` (synthetic test streams), `estimated` (probabilistic), and `unavailable` capabilities.

---

## 3. Starting Codebase & UI Framework Assessment

* **Frontend Engine:** Single Page Application (Vanilla JavaScript ES6+, HTML5, CSS3 Custom Properties) with zero external CDN dependencies, ensuring 100% air-gapped security compliance.
* **Desktop Application:** Python Tkinter / ttk (`src/camserv/desktop/console.py`) interfacing with backend REST and Windows SCM APIs via `DesktopServiceClient`.
* **Backend API:** FastAPI REST endpoints and WebSockets (`src/camserv/api/routes.py`).
* **Existing Automated Tests:** 372 / 372 automated test cases passing in the regression suite.
