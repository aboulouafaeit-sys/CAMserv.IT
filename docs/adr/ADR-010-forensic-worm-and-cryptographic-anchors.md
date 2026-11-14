# ADR-010: Forensic Immutable WORM Retention & OS/Hardware Cryptographic Anchor
**Status:** ACCEPTED  
**Date:** 2026-11-14  
**Context:** Software-only write-once rules can be bypassed if an attacker achieves administrative shell access on the host operating system, undermining legal chain of custody.  
**Decision:** Anchor evidentiary integrity in an OS-level Write-Once-Read-Many (WORM) storage architecture using Linux immutable file attributes (`chattr +i`), continuous SHA-256 Merkle hash chaining, and TPM 2.0-protected Ed25519 signing keys.  
**Consequences:** Sealed `.vault` archives cannot be altered or truncated even by root processes; independent offline verification tools (`camserv-verify`) can confirm non-tampering in court proceedings.
