# CAMserv Official Brand Identity & Design Guidelines
**Creative Direction & Industrial Brand Manual**  
**Version:** 1.0 (Commercial Enterprise Edition)  
**Author:** Chief Creative Director & Principal Brand Architect

---

## 1. Brand Strategy & Positioning

### 1.1 Brand Personality
CAMserv is **authoritative, mathematically precise, privacy-first, and technologically superior**.  
It is built for critical infrastructure operators, forensic investigators, corporate security executives, and municipal engineers who demand verifiable certainty over marketing hype.

### 1.2 Visual Philosophy: "The Coherent Prism"
Traditional security products default to tired, defensive clichés: padlocks, clip-art shields, all-seeing eyes, and cartoon cameras.  
CAMserv breaks with this cliché. Our visual mark is **The Sentinel Optical Aperture**—a six-segment interlocking geometric aperture formed by precision-refracted optical planes. It embodies:
1. **Dynamic Perspective:** Multi-camera situational awareness.
2. **Mathematical Precision:** Predictable kinematic vector estimation.
3. **Anonymity by Design:** Optical refraction masking personal data before persistent storage.
4. **Invariant Focus:** The central core dot representing cryptographic immutability.

---

## 2. Color Palette & Design Tokens

CAMserv utilizes an intentional **Tactical Deep Dark Mode** palette engineered for 24/7 security control room environments to minimize eye strain while highlighting actionable signals with clinical contrast.

### 2.1 Core Surfaces
| Token Name | Hex Code | Purpose |
| :--- | :--- | :--- |
| `--color-canvas` | `#0B0F19` | Deep obsidian background canvas |
| `--color-surface` | `#111827` | Panel and card background |
| `--color-surface-hover` | `#1E293B` | Interactive row and button hover state |
| `--color-border` | `#1F2937` | Subtle divider lines |
| `--color-border-active` | `#374151` | Focused and highlighted borders |

### 2.2 Semantic & Functional Accents
| Token Name | Hex Code | Meaning / Utilization |
| :--- | :--- | :--- |
| `--color-cyber-cyan` | `#06B6D4` | Primary brand accent; active camera streams, telemetry |
| `--color-emerald` | `#10B981` | Normal status, verified events, healthy hardware |
| `--color-amber` | `#F59E0B` | Warning, medium severity events, pending human review |
| `--color-crimson` | `#EF4444` | Critical events, fall detection, tamper triggers |
| `--color-indigo` | `#6366F1` | Machine learning inference, model version indicators |

### 2.3 Typography Scale
* **Display / UI Wordmark:** `Inter`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, sans-serif.
* **Forensic / Telemetry Data:** `JetBrains Mono`, `Fira Code`, `Consolas`, monospace. All coordinates, hashes, timestamps, and confidence scores MUST render in monospace with tabular figures (`font-variant-numeric: tabular-nums`).

---

## 3. Logo Assets & Sizing Rules

### 3.1 Primary Mark Hierarchy
1. **Master Horizontal Logo (`logo-primary-dark.svg`):** Used in navigation headers, documentation headers, and software splash screens.
2. **Sentinel Aperture Mark (`logo-symbol.svg`):** Standalone app launcher icon, packaging insignia, hardware faceplate badge.
3. **Monochrome Engraving Variant (`logo-monochrome.svg`):** Laser-engraved NVR chassis, thermal receipts, single-color packaging prints.
4. **Optimized Favicon (`favicon.svg`):** High-legibility 32x32 rounded badge for browser tabs and mobile home screens.

### 3.2 Clear Space & Proportions
* The logo must always maintain an exclusion zone equal to at least half the height of the central aperture mark ($0.5H$) on all four sides.
* Minimum digital display size: 24px height for symbol mark; 160px width for horizontal wordmark.
* Never warp, skew, recolor with unapproved gradients, or encase the logo inside a generic shield.
