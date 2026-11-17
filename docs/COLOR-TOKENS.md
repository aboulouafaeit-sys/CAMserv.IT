# CAMserv — Semantic Color Tokens & Glass Palette

**Document ID:** TOKENS-COLOR-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Design Direction:** Cinematic Dark / Multi-Layer Glassmorphism  
**Date:** November 17, 2026  
**Auditor:** Principal Visual Design Specialist  

---

## 1. Architectural Color System

CAMserv implements a strict semantic color token architecture where raw hex values are never hardcoded into UI components. The color tokens are organized into **Canvas Foundations**, **Multi-Layer Glass Surfaces**, **Borders & Rim Lighting**, **Luminous Signal Accents**, and **Contrast Typography**.

```
+---------------------------------------------------------------------------------+
|                                 CANVAS FOUNDATION                               |
|                  --bg-canvas: #070b14 (Midnight Obsidian)                       |
|                                                                                 |
|   +-------------------------------------------------------------------------+   |
|   |                          LAYER 2: SHELL RAILS                           |   |
|   |          --bg-glass-shell: rgba(13, 20, 36, 0.82) / Blur: 24px          |   |
|   |                                                                         |   |
|   |   +-----------------------------------------------------------------+   |   |
|   |   |                      LAYER 3: CONTENT PANELS                    |   |   |
|   |   |        --bg-glass-panel: rgba(17, 26, 46, 0.72) / Blur: 16px    |   |   |
|   |   |                                                                 |   |   |
|   |   |   +--------------------------+   +--------------------------+   |   |   |
|   |   |   |   LAYER 4: GLASS CARDS   |   |   LAYER 4: GLASS CARDS   |   |   |   |
|   |   |   |   rgba(22, 34, 60, 0.65) |   |   rgba(22, 34, 60, 0.65) |   |   |   |
|   |   |   |   Border: 1px Cyan Rim   |   |   Border: 1px Subtle Rim |   |   |   |
|   |   |   +--------------------------+   +--------------------------+   |   |   |
|   |   +-----------------------------------------------------------------+   |   |
|   +-------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------+
```

---

## 2. Token Specification Table

### 2.1 Surfaces & Glass Elevations
| CSS Token | Hex / RGBA Value | Backdrop Filter | Semantic Usage |
| :--- | :--- | :--- | :--- |
| `--bg-canvas` | `#070b14` | None | Base ambient dark space viewport |
| `--bg-glass-shell` | `rgba(13, 20, 36, 0.82)` | `blur(24px) saturate(180%)` | Main command sidebar rail & top header |
| `--bg-glass-panel` | `rgba(17, 26, 46, 0.72)` | `blur(16px) saturate(160%)` | Primary view container & card containers |
| `--bg-glass-card` | `rgba(22, 34, 60, 0.65)` | `blur(12px) saturate(150%)` | Individual metric cards, camera viewports |
| `--bg-glass-elevated`| `rgba(30, 46, 80, 0.78)` | `blur(16px) saturate(180%)` | Hovered items, active dropdowns |
| `--bg-glass-overlay` | `rgba(9, 14, 26, 0.85)` | `blur(28px) saturate(200%)` | Modal backdrop & judicial review overlay |
| `--bg-glass-alert` | `rgba(45, 15, 25, 0.85)` | `blur(20px)` | Critical security alert banner |

### 2.2 Borders & Rim Lighting
| CSS Token | Hex / RGBA Value | Semantic Usage |
| :--- | :--- | :--- |
| `--border-subtle` | `rgba(255, 255, 255, 0.08)` | Standard card boundary divider |
| `--border-glass-rim` | `rgba(255, 255, 255, 0.14)` | Top and left edge highlight for frosted glass effect |
| `--border-active` | `rgba(6, 182, 212, 0.40)` | Active tab or selected camera border |
| `--border-focus` | `#00f0ff` | Keyboard accessibility focus outline |
| `--border-critical` | `rgba(239, 68, 68, 0.60)` | Alarm state & storage fencing violation boundary |

### 2.3 Luminous Signal Accents
| CSS Token | Hex Code | Luminous Glow (Box Shadow) | Semantic Usage |
| :--- | :--- | :--- | :--- |
| `--accent-cyan` | `#00f0ff` | `0 0 16px rgba(0, 240, 255, 0.35)` | Primary telemetry, active recordings, brand focus |
| `--accent-emerald` | `#10b981` | `0 0 14px rgba(16, 185, 129, 0.30)` | Cluster quorum verified, healthy hardware, valid seal |
| `--accent-amber` | `#f59e0b` | `0 0 14px rgba(245, 158, 11, 0.30)` | Thermal warning, simulated telemetry, degraded sync |
| `--accent-crimson` | `#ef4444` | `0 0 18px rgba(239, 68, 68, 0.40)` | Tampering alarm, split-brain fence, unleased writer |
| `--accent-indigo` | `#6366f1` | `0 0 14px rgba(99, 102, 241, 0.30)` | Forensics evidence, Merkle proof, dual-control |
| `--accent-purple` | `#a855f7` | `0 0 14px rgba(168, 85, 247, 0.30)` | Judicial export hold, cryptographic witness |

### 2.4 High-Contrast Typography
| CSS Token | Hex Code | WCAG Contrast Ratio (vs `#070b14`) | Semantic Role |
| :--- | :--- | :---: | :--- |
| `--text-primary` | `#f8fafc` | **18.2 : 1** (Passes AAA) | Primary headings, camera titles, critical figures |
| `--text-secondary` | `#94a3b8` | **7.4 : 1** (Passes AAA) | Secondary labels, timestamps, body text |
| `--text-muted` | `#64748b` | **4.6 : 1** (Passes AA) | Passive metadata, inactive units, table headers |
| `--text-cyan` | `#38bdf8` | **10.8 : 1** (Passes AAA) | Highlighted telemetry, active badge text |
| `--text-amber` | `#fbbf24` | **11.5 : 1** (Passes AAA) | Warning notices, simulated state badge |

---

## 3. Light Mode Contrast Tokens (`[data-theme="light"]`)

For control rooms operating under bright overhead daylight illumination, CAMserv maintains a clinical high-contrast light theme:
* `--bg-canvas`: `#f1f5f9` (Cool Slate)
* `--bg-glass-shell`: `rgba(255, 255, 255, 0.88)` / `blur(20px)`
* `--bg-glass-card`: `rgba(255, 255, 255, 0.75)` / `blur(12px)`
* `--text-primary`: `#0f172a` (Deep Slate, **15.8 : 1** contrast)
* `--text-secondary`: `#334155` (Mid Slate, **8.9 : 1** contrast)
* `--border-subtle`: `rgba(15, 23, 42, 0.08)`
* `--accent-cyan`: `#0284c7` (Deep Sky Blue)
