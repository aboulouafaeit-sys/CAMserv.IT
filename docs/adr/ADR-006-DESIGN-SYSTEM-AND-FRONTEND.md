# ADR-006: CAMserv Design System and Enterprise Web Console Architecture

## Status
Accepted

## Context
Commercial viability requires an intuitive, high-performance, visually commanding product experience. Operators, security directors, and compliance auditors require unified visual interfaces rather than raw REST API endpoints. Traditional generic surveillance dashboards suffer from excessive cognitive load, cluttered panels, and lack of visual polish.

## Decision
1. Establish the **CAMserv Design System**:
   - Palette: Deep tactical dark mode (`#0B0F19` canvas, `#111827` surface, `#1F2937` borders) with high-contrast functional accents: Cyber Emerald (`#10B981`) for normal/verified states, Amber (`#F59E0B`) for attention/warnings, Crimson (`#EF4444`) for critical emergencies, and Electric Cyan (`#06B6D4`) for system telemetry.
   - Typography: Clean neo-grotesque sans-serif (`Inter`, system-ui) paired with tabular monospace (`JetBrains Mono`, `Fira Code`) for forensic timestamps, hash digests, and telemetry.
   - Original Vector Identity: A custom-crafted geometric aperture/optical refraction symbol avoiding cliché surveillance tropes (no generic clip-art eyes, padlocks, or shields).
2. Build the **CAMserv Enterprise Web Console** as a responsive, zero-dependency, high-speed single-page web application mounted directly onto FastAPI at `/` and `/console`.
3. Provide dedicated views for all 12 official product screens:
   1. Executive Overview
   2. Live Monitoring
   3. Camera Management
   4. Intelligent Event Center
   5. Anonymous Tracking Visualization
   6. Incident Investigation
   7. Evidence Vault
   8. Analytics & Reports
   9. Device & NVR Integration
   10. Security & Access Control
   11. System Health & Telemetry
   12. Deployment & Configuration
4. Ground every screen in live FastAPI endpoints, providing real-time WebSocket feeds, empty states, loading indicators, error boundaries, and permission-aware role controls.

## Consequences
- Positive: World-class, commercially competitive user experience; zero node/npm build complexity required at runtime (pure web standards); lightning-fast load times.
- Negative: Requires careful CSS and vanilla TypeScript/ES6 component modularity.
