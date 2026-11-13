# ADR-004: Digital Forensics, Asymmetric Signatures, and Evidence Chain-of-Custody

## Status
Accepted

## Context
While the existing evidence store implements AES-256-GCM encryption and SHA-256 hash chaining, a symmetric hash alone does not provide non-repudiation if an attacker obtains master key access or compromises the server process. Digital forensics in legal jurisdictions requires verifiable proof that exported video manifests were signed by a specific hardware or server key at a specific time, with a standalone verification utility that does not depend on the server backend.

## Decision
1. Introduce asymmetric digital signatures (Ed25519) into evidence packaging (`src/camserv/storage/forensics.py`).
2. Package evidence as standard ZIP archives containing:
   - Encrypted or obfuscated video payload chunks.
   - Evidence metadata JSON including camera ID, time range, triggering event ID, and supporting detection bounding boxes.
   - SHA-256 hash manifest of all enclosed artifacts.
   - Ed25519 digital signature of the manifest created using the server's private key.
   - RFC 3161 compliant timestamp token placeholder / HMAC time token.
   - Complete chain-of-custody transfer log.
3. Provide a standalone verification CLI utility (`camserv verify-evidence <package.zip> --public-key <key.pem>`) capable of running offline on any auditor workstation.

## Consequences
- Positive: Courtroom-grade forensic chain of custody; independent auditability without running CAMserv infrastructure.
- Negative: Additional key management lifecycle for server asymmetric keypairs.
