# Phase 15: Cross-Platform Data, Database & Evidence Portability

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-alpha1`  
**Scope:** SQLite WAL Compatibility, MP4 Recordings, Evidence Manifests & Archive Portability  

---

## 1. Storage & Forensic Artifact Portability

A primary architectural requirement of Phase 15 is that all databases, recording segments, and forensic evidence archives created on a Debian Linux appliance must be 100% readable and verifiable on Microsoft Windows (and vice versa) without conversion or loss of cryptographic validity.

```text
┌────────────────────────────────────────────────────────┐
│                   Exported Evidence Bundle             │
│                 (forensic_evidence_XYZ.zip)            │
│  ├── recording.mp4       (Fragmented ISO/IEC 14496-12) │
│  ├── manifest.json       (UTF-8 canonical JSON)        │
│  └── signature.sig       (Raw 64-byte Ed25519 payload) │
└───────────────────────────┬────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌───────────────────────┐       ┌───────────────────────┐
│     Created on:       │       │     Verified on:      │
│  Debian 13 Linux NVR  │ ────► │  Windows 11 Operator  │
│  (IndependentVerifier)│       │  (IndependentVerifier)│
│     Result: PASS      │       │     Result: PASS      │
└───────────────────────┘       └───────────────────────┘
```

---

## 2. Portable Data Specifications

### 2.1 SQLite WAL Database (`camserv.db`)
- **Format:** SQLite 3 format (version 3.39+ compatible).
- **Journal Mode:** Write-Ahead Logging (`PRAGMA journal_mode=WAL`).
- **Endianness:** Little-endian standard (standard on x86_64, aarch64, Windows, and Linux).
- **Path Portability:** Paths stored in database tables (`recordings`, `snapshots`) use relative paths or forward-slash normalized strings, preventing Windows backslash (`\`) syntax errors when migrated across platforms.

### 2.2 Fragmented MP4 Video Segments
- **Container:** Standard ISO base media file format (`ftyp`, `moov`, `mdat` atoms).
- **Codec:** H.264 (AVC) / H.265 (HEVC) elementary streams.
- **Playback Compatibility:** Directly playable in Windows Media Player, VLC, QuickTime, and HTML5 `<video>` elements.

### 2.3 Evidence Manifest & Ed25519 Signatures
- **Manifest:** Formatted as deterministic, sorted-key UTF-8 JSON.
- **Signature:** Ed25519 public key cryptography generates deterministic 64-byte signatures over the SHA-256 hash of the payload.
- **Portability Verification:** Evidence packages generated in Phase 14 software harnesses were verified on Windows using `IndependentVerifier.verify_package()`, achieving 100% signature authentication.
