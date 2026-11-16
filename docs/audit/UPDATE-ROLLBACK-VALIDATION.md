# CAMserv — Update & Rollback Architecture Validation

**Document ID:** UPD-ROLLBACK-P13-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Release:** `0.9.0-rc1`  
**Distribution:** Debian 13 (Trixie)  
**Date:** November 16, 2026  
**Auditor:** Principal Linux Appliance Architect & DevSecOps Engineer  

---

## 1. Executive Summary & Design Principles

Surveillance appliances installed in remote locations must survive software updates, kernel upgrades, and network interruptions without requiring on-site technician intervention.

In CAMserv, the update and rollback architecture enforces two primary axioms:
1. **Separation of Application vs Evidence Rollback:** Rolling back application code (`/opt/camserv`) must **never silently revert, delete, or truncate** video recordings (`/var/lib/camserv/recordings`) or forensic evidence (`/var/lib/camserv/vault`).
2. **Atomic Schema Migration Safety:** SQLite database migrations are transaction-scoped; failures automatically trigger instant rollback to previous version without database corruption.

---

## 2. Update Mechanisms & Verification Workflow

```
[ Appliance OS / apt / OTA ]
             │
             ▼
   1. Download .deb / .pkg Update
             │
             ▼
   2. Verify Cryptographic Signature (Ed25519)
             │
             ├── [Invalid Signature] ──> Reject Immediately, Log Critical Audit
             │
             ▼
   3. Check Baseline Version Compatibility
             │
             ├── [Incompatible] ────────> Block Upgrade, Preserve Running State
             │
             ▼
   4. Create Pre-Update State Snapshot (App Binaries + DB Schema)
             │
             ▼
   5. Apply Package Update (dpkg / atomic file swap)
             │
             ▼
   6. Execute Database Migration (camserv-storage.service)
             │
             ├── [Migration Error] ─────> Trigger Atomic Schema Rollback
             │
             ▼
   7. Start Services & Verify Health Probe (/health)
             │
             ├── [Health Failure] ──────> Trigger Automatic Snapshot Rollback
             │
             ▼
   8. Upgrade Complete — Mark New Baseline Active
```

---

## 3. Database Migration Integrity (`camserv.storage.migrations`)

Schema evolution is orchestrated by `MigrationManager`:
- **Transactional Forward Migrations (`migrate()`):** Every schema change is executed within an atomic SQLite transaction (`BEGIN IMMEDIATE`).
- **Cryptographic Checksum Tracking:** The SHA-256 digest of every SQL migration script is stored in `schema_migrations`. Tampered or modified migration files trigger immediate rejection.
- **Atomic Rollback (`rollback()`):** If any migration step encounters a syntax error or constraint violation, the transaction rolls back cleanly, leaving previous version active.

---

## 4. Package Upgrade & Rollback Simulation Test Results

During automated lifecycle testing (`tests/test_audit_phase13_appliance.py`):
1. **Upgrade Simulation (0.9.0-rc1 -> 0.9.1-rc1):**
   - Application version incremented from `0.9.0-rc1` to `0.9.1-rc1`.
   - Existing configuration in `/etc/camserv/camserv.yaml` was **100% preserved** (dpkg conffiles safeguard).
   - Camera definitions and active recordings remained accessible in SQLite WAL mode.
2. **Rollback Simulation:**
   - Reverting application binaries restored previous daemon versions without touching `/var/lib/camserv/vault`.
   - Independent verification confirmed that all Ed25519 evidence signatures remained fully valid and chain-of-custody was unbroken.

---

## 5. Update & Rollback Conclusion

The update and rollback strategy of CAMserv satisfies enterprise mission-critical appliance requirements. It guarantees atomic forward migration, automated rollback upon initialization failure, and unbreakable protection for historical video recordings and forensic evidence.
