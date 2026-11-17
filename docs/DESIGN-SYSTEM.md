# CAMserv — Enterprise Glassmorphism Design System Specification

**Document ID:** SPEC-DESIGN-SYSTEM-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Visual Direction:** Cinematic Dark / Multi-Layer Glassmorphism  
**Date:** November 17, 2026  
**Auditor:** Principal Enterprise UI/UX Systems Architect  

---

## 1. System Overview

The CAMserv Enterprise Design System provides a coherent, scalable, and mathematically sound visual language for mission-critical surveillance, video forensics, and distributed cluster operations. It formalizes multi-layer glass elevation, luminous rim lighting, clinical typography, and performance-bounded motion.

---

## 2. Multi-Layer Glassmorphism Architecture

The interface is structured into discrete translucent surfaces with controlled refractive depth:

```
+---------------------------------------------------------------------------------+
| LEVEL 1: BASE CANVAS                                                            |
| Background: #070b14                                                            |
| Ambient Mesh: radial-gradient(ellipse at 20% 0%, rgba(0,240,255,0.06), transparent) |
+---------------------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------------------+
| LEVEL 2: COMMAND SHELL RAILS (Sidebar & Top Command Bar)                         |
| Background: rgba(13, 20, 36, 0.85) | Backdrop-Filter: blur(24px) saturate(180%)   |
| Border: 1px solid rgba(255, 255, 255, 0.08)                                    |
+---------------------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------------------+
| LEVEL 3: CONTENT REGIONS & SECTION PANELS                                       |
| Background: rgba(17, 26, 46, 0.72) | Backdrop-Filter: blur(16px) saturate(160%)   |
| Border: 1px solid rgba(255, 255, 255, 0.06)                                    |
+---------------------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------------------+
| LEVEL 4: INTERACTIVE GLASS CARDS & VIEWPORT TILES                               |
| Background: rgba(22, 34, 60, 0.65) | Backdrop-Filter: blur(12px)                 |
| Rim Light: linear-gradient(135deg, rgba(255,255,255,0.12), rgba(0,240,255,0.1)) |
| Box Shadow: 0 8px 32px rgba(0, 0, 0, 0.35)                                     |
+---------------------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------------------+
| LEVEL 5: FLOATING HUDs & OVERLAY CONTROLS                                       |
| Background: rgba(9, 14, 26, 0.88) | Backdrop-Filter: blur(20px)                  |
| Border: 1px solid rgba(0, 240, 255, 0.30)                                       |
+---------------------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------------------+
| LEVEL 6: MODALS & JUDICIAL QUORUM SHEETS                                        |
| Backdrop Overlay: rgba(4, 7, 14, 0.80) with blur(16px)                         |
| Sheet Background: rgba(16, 24, 44, 0.95) | Border: 1px solid rgba(0,240,255,0.2) |
+---------------------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------------------+
| LEVEL 7: CRITICAL ALERTS & STORAGE FENCING BANNERS                              |
| Background: rgba(60, 15, 25, 0.92) | Border: 1px solid rgba(239, 68, 68, 0.8)   |
| Box Shadow: 0 0 24px rgba(239, 68, 68, 0.45)                                   |
+---------------------------------------------------------------------------------+
```

---

## 3. Luminous Accent System & Semantic Signatures

Every operational state maps to an unambiguous luminous visual signature:

| Operational State | Primary Accent | Accent Glow Signature | Semantic Meaning |
| :--- | :--- | :--- | :--- |
| **Normal / Recording** | `#00f0ff` (Cyan) | `0 0 12px rgba(0, 240, 255, 0.35)` | Active camera recording, valid lease, normal system state |
| **Quorum Committed** | `#10b981` (Emerald) | `0 0 12px rgba(16, 185, 129, 0.30)` | Cluster quorum verified ($Q \ge \lfloor N/2 \rfloor + 1$), valid witness seal |
| **Warning / Sim** | `#f59e0b` (Amber) | `0 0 12px rgba(245, 158, 11, 0.30)` | High CPU/thermal load, simulated synthetic feed, sync delay |
| **Alarm / Fenced** | `#ef4444` (Crimson) | `0 0 18px rgba(239, 68, 68, 0.40)` | Storage lease expired, stale writer fenced, physical tampering |
| **Forensic Evidence** | `#6366f1` (Indigo) | `0 0 12px rgba(99, 102, 241, 0.30)` | Ed25519 signed evidence package, Merkle root verification |
| **Judicial Hold** | `#a855f7` (Purple) | `0 0 12px rgba(168, 85, 247, 0.30)` | Dual-control export active, courtroom chain of custody |

---

## 4. Motion & Animation Standards

To protect critical surveillance frame acquisition and avoid operator distraction:
1. **Duration Scaling:**
   - Micro-interactions (hover, button click): `120ms - 150ms` ease-out.
   - Panel transitions (screen switch, drawer slide): `200ms - 250ms` cubic-bezier(0.16, 1, 0.3, 1).
   - Modal entrances: `200ms` cubic-bezier(0.16, 1, 0.3, 1).
2. **Zero Infinite GPU Loops:**
   - Pulse animations for live recording (`.live-pulse`) are lightweight CSS opacity transitions without continuous canvas redraw.
3. **Reduced Motion Compliance (`@media (prefers-reduced-motion: reduce)`):**
   - All transitions, transforms, and keyframe animations are disabled or converted to instantaneous opacity cuts.

---

## 5. Official Logo Preservation & Display Standards

* **Authoritative Asset:** `assets/branding/camserv-logo-transparent.png` (683x757 PNG, SHA-256 `b75ded3078026662`).
* **Display Container:**
  - Placed in `.brand-header` at exact height `38px` with proportional width constraint (`width: auto`, preserving natural aspect ratio $0.902$).
  - Clear space: Minimum $12\text{px}$ perimeter free of text, borders, or icons.
  - Backdrop: Rendered over dark glass shell (`--bg-glass-shell`) with subtle luminous drop shadow `filter: drop-shadow(0 2px 8px rgba(0, 240, 255, 0.25))`.
  - Zero modification: Prohibits redrawing, cropping, recoloring, or substitution.
