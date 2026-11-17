# CAMserv — Typography & Spatial Design Tokens

**Document ID:** TOKENS-TYPO-SPACE-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Visual Direction:** Cinematic Dark / Multi-Layer Glassmorphism  
**Date:** November 17, 2026  
**Auditor:** Principal Enterprise UX Architect  

---

## 1. Typographic Architecture

The CAMserv typographic hierarchy balances **clinical operational legibility** with **high-density forensic information display**. It enforces strict font stack separation:

1. **System Sans-Serif Stack (`--font-sans`):**  
   `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Helvetica Neue", Arial, sans-serif`  
   Optimized for high-speed scanning of navigation, alerts, titles, and button controls.
2. **Tabular Monospace Stack (`--font-mono`):**  
   `"JetBrains Mono", "Fira Code", "Cascadia Code", "Roboto Mono", Consolas, monospace`  
   Mandatory for all cryptographic hashes (SHA-256), IP addresses, RTSP URIs, FPS/bitrate metrics, timestamps, and epoch sequences to guarantee zero column jitter.

---

## 2. Modular Type Scale

| Level | CSS Token | Size / Line Height | Weight | Letter Spacing | Semantic Role |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Hero / Display** | `--text-3xl` | `26px / 32px` | 800 (Bold) | `-0.02em` | Major system status & brand header |
| **Section H1** | `--text-2xl` | `20px / 26px` | 700 (Bold) | `-0.01em` | Screen titles & modal headers |
| **Card Header H2** | `--text-xl` | `16px / 22px` | 600 (Semibold) | `0.00em` | Panel titles, camera names |
| **Subheader H3** | `--text-lg` | `14px / 20px` | 600 (Semibold) | `0.01em` | Widget category labels, table headers |
| **Body Primary** | `--text-base` | `13px / 18px` | 400 (Regular) | `0.01em` | Descriptive text, incident narratives |
| **Body Small** | `--text-sm` | `12px / 16px` | 400 (Regular) | `0.02em` | Secondary metadata, parameter values |
| **Micro / Badge** | `--text-xs` | `11px / 14px` | 700 (Bold) | `0.06em` | Status badges, tracking IDs, tags |
| **Forensic Hash** | `--font-mono` | `11.5px / 15px` | 500 (Medium) | `0.00em` | SHA-256 digests, Ed25519 signatures |

---

## 3. Spatial Scale (4px Base Grid)

CAMserv layouts align to a consistent 4-pixel rhythmic grid to prevent uneven padding and misaligned telemetry columns:

| Token | Pixels | Semantic Usage |
| :--- | :---: | :--- |
| `--space-1` | `4px` | Micro-gap between badge icon and label text |
| `--space-2` | `8px` | Button inline padding, compact card gap |
| `--space-3` | `12px` | Standard element spacing inside metric cards |
| `--space-4` | `16px` | Card internal padding, sidebar item gap |
| `--space-5` | `20px` | Header padding, grid gutters in camera matrix |
| `--space-6` | `24px` | Section margins, modal internal padding |
| `--space-8` | `32px` | Outer viewport padding on large displays (1080p/1440p) |
| `--space-12`| `48px` | Major dashboard segment separation |

---

## 4. Corner Radius & Elevation Depth

| Token | Radius Value | Semantic Surface Role |
| :--- | :---: | :--- |
| `--radius-xs` | `3px` | Status indicator pills, miniature tag badges |
| `--radius-sm` | `6px` | Form inputs, dropdown buttons, action triggers |
| `--radius-md` | `10px` | Glass metric cards, camera video viewports |
| `--radius-lg` | `16px` | Floating panels, incident drawers, modal sheets |
| `--radius-full` | `9999px` | Round avatars, pulse indicator halos, pill tabs |

---

## 5. Z-Index Layer Stack

```
Layer 7: Critical Alerts & Fencing Banners      (z-index: 1000)
Layer 6: Modal Windows & Judicial Quorum Dialogs (z-index: 900)
Layer 5: Floating HUDs, Tooltips, Dropdowns      (z-index: 800)
Layer 4: Interactive Overlays & Timeline Scrubber(z-index: 500)
Layer 3: Top Navigation Bar & Fixed Headers      (z-index: 100)
Layer 2: Command Sidebar Rail                    (z-index: 50)
Layer 1: Main Viewport Glass Canvas              (z-index: 1)
```
