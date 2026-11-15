# CAMserv Central Management & Fleet Architecture

**Document ID:** ARCH-CENTRAL-2026-001  
**Classification:** Distributed Systems Architecture Specification  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Overview and Topology

**CAMserv Central** is a distributed management and orchestration plane designed to coordinate hundreds of distributed CAMserv AI Appliances, Edge Nodes, and physical facilities from a centralized operations dashboard.

```
                                  ┌──────────────────────────────┐
                                  │       CAMserv Central        │
                                  │   (HQ Management Cluster)    │
                                  └──────────────┬───────────────┘
                                                 │
                   ┌─────────────────────────────┴─────────────────────────────┐
                   │ WAN Connection (Ed25519 Replay-Protected Envelopes)       │
                   ▼                                                           ▼
    ┌─────────────────────────────┐                             ┌─────────────────────────────┐
    │     Facility Site Alpha     │                             │      Facility Site Beta     │
    │ ┌─────────────────────────┐ │                             │ ┌─────────────────────────┐ │
    │ │  CAMserv Appliance 1    │ │                             │ │  CAMserv Appliance 2    │ │
    │ │  (Local NVR & AI Core)  │ │                             │ │  (Local NVR & AI Core)  │ │
    │ └───────────┬─────────────┘ │                             │ └───────────┬─────────────┘ │
    │             │               │                             │             │               │
    │    ┌────────┴────────┐      │                             │    ┌────────┴────────┐      │
    │    ▼                 ▼      │                             │    ▼                 ▼      │
    │ [Cam 1]           [Cam 2]   │                             │ [Cam 3]           [Cam 4]   │
    └─────────────────────────────┘                             └─────────────────────────────┘
```

---

## 2. Multi-Site Authorization Boundaries & Tenant Isolation

- **Server-Side Enforcement:** Device and site access controls are enforced within the `DeviceRegistry` (`src/camserv/central/registry.py`).
- **Role Scoping:**
  - `SUPER_ADMIN`: Global fleet-wide visibility across all organizations and sites.
  - `SITE_ADMIN` / `SITE_OPERATOR`: Cryptographically locked to specific authorized facility sites (`user_assigned_sites`). Attempts to query or command unauthorized sites return explicit `SiteAccessDeniedError` (HTTP 403).
- **Tenant Isolation:** Organizations maintain independent cryptographic keystores and database namespaces, preventing cross-organization data leakage.

---

## 3. Cryptographic Enrollment & Handshake

Appliance enrollment follows a zero-trust cryptographic challenge-response protocol:
1. **One-Time Enrollment Token:** Central generates a short-lived token binding the device identifier to an assigned site.
2. **Device Identity Generation:** The appliance generates an Ed25519 asymmetric key pair in local secure storage.
3. **Cryptographic Handshake:** Central issues a dynamic 32-byte cryptographic challenge. The appliance signs the challenge with its private key.
4. **Registration Confirmation:** Central verifies the signature against the appliance public key and seals the enrollment.

---

## 4. Resilient Distributed Communication & Store-and-Forward

- **Replay Defense:** Distributed communication envelopes contain monotonic UTC timestamps and unique UUID nonces. Messages older than 300 seconds or presenting duplicate nonces are rejected (`ReplayAttackError`).
- **Store-and-Forward Offline Buffer:** If WAN connectivity between an edge appliance and CAMserv Central is interrupted, local recording and AI analytics continue uninterrupted. Telemetry digests and incident alerts are queued in a persistent SQLite buffer and automatically synchronized upon link restoration.
- **WAN Data Minimization:** Transmission of raw surveillance video over wide-area links is programmatically blocked (`DataMinimizationViolationError`). Only structured numerical metadata, object counts, and cryptographic hashes cross WAN boundaries.
