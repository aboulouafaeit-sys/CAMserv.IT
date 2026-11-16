# Release Notes: CAMserv 0.10.0-rc2

**Release Candidate:** `0.10.0-rc2`  
**Previous Release Candidate:** `0.10.0-rc1`  
**Release Date:** November 16, 2026  
**Target Architectures:** AMD64, ARM64  
**Target Platforms:** Windows 11 x64, Windows 10 x64, Debian 12 Bookworm, Debian 13 Trixie  

---

## 1. Overview

CAMserv `0.10.0-rc2` is the hardened Enterprise Release Candidate of the CAMserv Advanced Security Intelligence Platform. Building on the multi-node federation capabilities introduced in `0.10.0-rc1`, `0.10.0-rc2` introduces formal distributed consensus safety, split-brain immunity, monotonic resource fencing, RFC 8785 canonical evidence sealing, active zero-trust session revocation, and multi-tenant boundary isolation.

---

## 2. Key Enhancements & New Features

### 2.1 Monotonic Term Consensus & Split-Brain Prevention
- **Strict Majority Quorum:** Cluster coordinator enforces $\lfloor N/2 \rfloor + 1$ quorum threshold. Minority network partitions can no longer elect leaders or execute rogue channel failovers.
- **Monotonic Cluster Terms:** All elections and cluster decisions advance monotonically tagged terms, preventing replay or stale leader commands.
- **Cryptographic Fencing Tokens:** Leadership handoffs generate cryptographically verified fencing tokens.

### 2.2 Camera Ownership Fencing & Dual-Writer Elimination
- **Monotonic Assignment Epochs:** Each camera channel migration increments an assignment epoch.
- **Writer Fencing Validation:** Recorders verify their epoch against the cluster directory before writing video segments. Stale writers attempting dual-writer operations are fenced with `FencedWriterError`.

### 2.3 Distributed Forensic Witness Hardening
- **RFC 8785 Canonical Serialization:** Replaced string delimiters with deterministic lexicographical JSON serialization under domain separation `CAMSERV-FORENSIC-SEAL-V2`.
- **Anti-Replay Nonces:** Attestation records contain cryptographic nonces tracked across the witness cluster to eliminate signature replay attacks.
- **Cryptographic Merkle Inclusion Proofs:** Verifiable binary proofs validating that individual video segments belong to an authentic cluster Merkle root.

### 2.4 Zero-Trust Mutual TLS with Active Session Severing
- **SAN / Common Name Identity Binding:** Client certificates are strictly validated against registered node identities.
- **Active In-Flight Session Termination:** Gateway maintains an active socket registry. Adding a node to the CRL immediately severs all in-flight TCP/TLS connections.

### 2.5 Multi-Tenant Boundary Enforcement
- Hard isolation between tenant domains prevents foreign nodes from joining clusters, intercepting streams, or participating in witness quorum.

### 2.6 Dynamic Version Consistency
- API `/health` route and OpenAPI documentation now dynamically report the canonical platform release version (`0.10.0-rc2`).

---

## 3. Defects Remediated in this Release Candidate

| Issue ID | Component | Summary of Fix |
| :--- | :--- | :--- |
| **FINDING 18-01** | `central/cluster.py` | Enforced strict majority quorum $> N/2$ and monotonic term fencing |
| **FINDING 18-02** | `central/cluster.py` | Implemented camera assignment epochs and writer fencing checks |
| **FINDING 18-03** | `central/replication.py` | Migrated to RFC 8785 canonical JSON, anti-replay nonces, and Merkle proofs |
| **FINDING 18-04** | `central/mtls.py` | Added active session tracking and instant connection termination on revocation |
| **FINDING 18-05** | `central/cluster.py` | Enforced strict multi-tenant boundaries during node registration & attestation |
| **FINDING 18-06** | `api/app.py`, `routes.py` | Dynamically bound API health endpoints to canonical `camserv.__version__` |

---

## 4. Test & Qualification Summary

- **Automated Test Suite:** 347 passed / 347 total (100.0% pass rate).
- **Chaos Fault Scenarios:** 25 / 25 scenarios verified safe under leader crashes, partitions, and bitstream corruption.
- **Production Audit Invariant:** `logs/audit.jsonl` verified inviolate (20,977 bytes, SHA-256 `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`).
