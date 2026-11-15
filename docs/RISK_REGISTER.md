# CAMserv Engineering Risk Register

**Document ID:** RISK-REGISTER-2026-001  
**Classification:** Engineering Governance & Risk Management  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Risk Evaluation Matrix

Risks are assessed according to Impact (1-5) and Probability (1-5), yielding a composite Risk Score ($1 - 25$).

| Risk ID | Category | Description | Probability | Impact | Score | Mitigation Strategy |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- |
| **RSK-01** | **Performance** | High disk I/O contention during simultaneous multi-camera 4K continuous recording. | 3 | 4 | **12** | Implement RAM write-buffering before disk flush; decouple indexing from write paths; utilize direct non-blocking asynchronous file writers. |
| **RSK-02** | **Privacy** | Accidental exposure of unmasked raw video during streaming or timeline playback. | 2 | 5 | **10** | Centralized Fail-Closed Privacy Pipeline applied at ingestion gate; operational streams consume only post-privacy buffers. |
| **RSK-03** | **Database** | SQLite database locking errors under high-concurrency event and segment ingestion. | 3 | 3 | **9** | Enforce SQLite Write-Ahead Logging (WAL) mode; set busy timeout to 10.0s; batch segment write operations. |
| **RSK-04** | **Reliability** | Abrupt service termination or power cut leaving incomplete MP4 files unfinalized. | 3 | 4 | **12** | Use fragmented MP4 (fMP4) or segmented TS chunks; implement startup scanner to repair `.part` files automatically. |
| **RSK-05** | **Security** | Replay or spoofing attacks on distributed WAN communication links. | 2 | 4 | **8** | Implement Ed25519-signed message envelopes with UUID nonces and strict 300s timestamp freshness verification. |
| **RSK-06** | **Hardware** | Thermal runaway on fanless edge appliances under heavy neural inference load. | 3 | 3 | **9** | Implement thermal-aware dynamic load shedding: automatically drop frame rate and non-critical analytics when GPU die exceeds $85^\circ\text{C}$. |
| **RSK-07** | **Compliance** | Failure to adhere to GDPR retention limits leading to regulatory penalties. | 2 | 5 | **10** | Automated background retention purge job enforcing 48-hour continuous recording ceiling unless locked under judicial hold. |
| **RSK-08** | **Supply Chain** | Compromised third-party Python package or model weight file. | 2 | 4 | **8** | Automated CycloneDX SBOM generation; pinned package hashes; strict Ed25519 update manifest signature checks. |
