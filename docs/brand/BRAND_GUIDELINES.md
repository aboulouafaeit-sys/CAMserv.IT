# CAMserv Official Brand Identity & Design Guidelines

**Creative Direction & Commercial Brand Manual**  
**Version:** 2.0 (Official AI-Illustrated Edition)  
**Author:** Chief Creative Director & AI Visual Design Specialist

---

## 1. Brand Strategy & Positioning

### 1.1 Brand Personality
CAMserv is **authoritative, mathematically precise, privacy-first, and technologically superior**.  
It is engineered for critical infrastructure operators, forensic investigators, corporate security executives, and municipal engineers who demand verifiable certainty over marketing hype.

### 1.2 Visual Philosophy: "The Cybernetic Sentinel"
CAMserv has superseded all generic geometric clip-art and assembled vectors with an original, professionally illustrated visual identity generated via **Google Imagen 3**.

The core visual mark is the **Vigilant Sentinel Crest**—an organic-cybernetic synthesis combining:
1. **The Raptor Crest:** Represents vigilant oversight, aerial awareness, and high-altitude situational command.
2. **The Optical Aperture Iris:** Represents video stream acquisition, precision lenses, and real-time optical tracking.
3. **Neural Circuit Nodes:** Highlights on-device machine learning inference, kinematic velocity estimation, and graph-based event reasoning.
4. **The Protective Shield Geometry:** Emphasizes non-biometric privacy protection, cryptographic sealing (AES-256-GCM, SHA-256 hash chains), and strict GDPR conformity.

---

## 2. Color Palette & Design Tokens

CAMserv utilizes an intentional **Tactical Command Dark Mode** palette engineered for 24/7 security control room environments to minimize eye fatigue while highlighting actionable signals with clinical contrast. A high-contrast **Light Mode** is provided for daytime dispatch and executive briefing environments.

### 2.1 Core Surfaces & Canvases
| Token Name | Hex Code | Purpose |
| :--- | :--- | :--- |
| `--color-canvas-dark` | `#0A0F1D` | Deep obsidian command canvas |
| `--color-surface-dark` | `#111827` | Primary card and panel surface |
| `--color-surface-hover` | `#1F2937` | Interactive row and button hover state |
| `--color-border-dark` | `#1E293B` | Subtle technical boundary lines |
| `--color-canvas-light` | `#F8FAFC` | High-contrast daytime canvas |
| `--color-surface-light` | `#FFFFFF` | Daytime panel surface |

### 2.2 Semantic Accents & Telemetry
| Token Name | Hex Code | Meaning / Utilization |
| :--- | :--- | :--- |
| `--color-electric-cyan` | `#00E5FF` | Primary brand accent; active camera streams, telemetry |
| `--color-cyber-indigo` | `#3B82F6` | Deep learning models, inference accelerators, tracking vectors |
| `--color-emerald` | `#10B981` | Healthy system status, verified evidence, GDPR compliance |
| `--color-amber` | `#F59E0B` | Medium severity events, pending human verification (HITL) |
| `--color-crimson` | `#EF4444` | High/Critical alarms, restricted zone violations, tamper alerts |

### 2.3 Typography Scale
* **Display / UI Wordmark:** `Inter`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, sans-serif.
* **Forensic / Telemetry Data:** `JetBrains Mono`, `Consolas`, monospace. All coordinates, hashes, timestamps, and confidence scores MUST render in monospace with tabular figures (`font-variant-numeric: tabular-nums`).

---

## 3. Official Master Brand Asset Suite

All primary visual assets are high-resolution PNGs residing in `assets/branding/` and `src/camserv/web/assets/`:

```
assets/branding/
├── camserv-logo-master.png           # 1024x1024 Master Illustrated Artwork (Obsidian)
├── camserv-logo-transparent.png      # 1024x1024 Isolated Falcon Crest (Alpha Channel)
├── camserv-logo-dark-background.png  # 1024x1024 Dark Mode Console Emblem
├── camserv-logo-light-background.png # 1024x1024 Light Mode High-Contrast Emblem
├── camserv-symbol.png                # 1024x1024 Standalone Brand Symbol
├── camserv-wordmark.png              # 800x200 Horizontal Lockup with Typography
├── camserv-app-icon.png              # 512x512 Launcher & Container Icon
├── camserv-favicon.png               # 32x32 Favicon PNG
├── favicon.ico                       # Multi-Resolution Windows/Web Icon (16-256px)
└── favicon-{16,32,48,64,128,192,256,512,1024}x...png
```

---

## 4. Usage Rules & Clear Space

### 4.1 Safe Clear Space
Maintain a clear margin of at least $0.25 \times X$ (where $X$ is the emblem width) around all sides of the mark. No typography, interface controls, or competing graphics may infringe into this boundary.

### 4.2 Prohibited Alterations
* **DO NOT** stretch, skew, or alter the 1:1 aspect ratio of the emblem.
* **DO NOT** recolor the emblem with arbitrary unapproved tints.
* **DO NOT** place the dark emblem against busy, multi-colored photographic backgrounds without a translucent backing plate.
* **DO NOT** substitute generic clip-art or geometric shapes for the official illustrated mark.
