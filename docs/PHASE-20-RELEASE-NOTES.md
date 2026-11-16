# CAMserv Release Notes — Version 0.10.0 (Pre-LTS Qualification)

**Release Identity:** CAMserv `0.10.0`  
**Classification:** Pre-LTS Qualification Release  
**Release Date:** November 16, 2026  
**Git Baseline:** `d33c87d7cfa7dfa2620fec686ba156813ec027ae`  

---

## Key Highlights & Architectural Deliverables

### 1. Mathematical Quorum Calculation & Split-Brain Elimination
* Enforces strict majority quorum $Q = \lfloor N/2 \rfloor + 1$ against configured cluster size (`expected_cluster_size`).
* Eliminates split-brain on cold boot: isolated single nodes booting alone in a multi-node cluster refuse to elect themselves leader.
* Minority partitions are barred from electing leaders, accepting camera assignments, or granting storage leases.

### 2. Comprehensive StorageLease Writer Fencing
* Enforces time-bounded, epoch-tagged `StorageLease` checks on frame ingestion, segment creation, and crash recovery.
* Stale writers attempting to write frames to storage raise `FencedWriterError`.
* Unleased segments written during network partitions are automatically isolated to `.quarantined.mp4`, protecting majority-committed evidence from corruption or overwrite.

### 3. Fail-Closed Durable State Persistence
* Synchronous disk flush (`os.fsync`) and atomic replace guarantee crash consistency across host reboots.
* Corrupted consensus or nonce cache files raise `CorruptedConsensusStateError` and `CorruptedReplicationStateError`, failing closed to prevent term rewind or replay attacks.

### 4. Forensic Evidence Quarantine & Restoration
* Guarantees byte-for-byte SHA-256 hash preservation when incomplete segments are quarantined.
* Introduces privileged operator review and restoration workflow (`get_quarantined_segments`, `restore_quarantined_segment`).

### 5. Cross-Platform Native Platform Support
* **Windows 11:** Full SCM Session 0 Service lifecycle, Tkinter Desktop Console, DirectShow/MSMF optical camera ingestion, DPAPI credential protection.
* **Debian 12/13:** Strict Systemd security sandboxing (`ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes`), unprivileged `camserv:camserv` user daemon, multi-arch packages.
* **Test Suite:** 372 automated unit, integration, and chaos tests passing with 100.0% success rate.
