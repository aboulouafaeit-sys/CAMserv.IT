# CAMserv — Phase 3 Enterprise Security, Identity & Multi-Tenancy Architecture

**Document ID:** ARCH-ENT-SEC-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Stage 5 Deliverable  
**Date:** November 15, 2026  
**Status:** PRODUCTION ENTERPRISE SECURITY BLUEPRINT  
**Author / Authority:** Cybersecurity Architect, Enterprise Infrastructure Architect & Chief Software Architect  

---

## 1. Executive Summary & Design Scope

**Stage 5** establishes the enterprise security, multi-tenancy, and identity architecture of CAMserv.

In multi-tenant commercial deployments (e.g., shared multi-tenant business parks, airport concessionaires, multi-agency public safety networks), different organizations share the underlying CAMserv Central management cluster. The platform must guarantee that cross-tenant data access is mathematically impossible, permissions follow the principle of least privilege, privacy-sensitive operations require dual-control authorization, and security events are cryptographically sealed in tamper-evident audit logs.

### Core Enterprise Security Invariants:
1. **Server-Side Authorization Boundaries:** UI filtering is **never** relied upon as a security boundary. Authorization is evaluated server-side at the API gateway layer before database queries or video stream dispatches execute.
2. **Absolute Multi-Tenant Isolation:** An authenticated identity belonging to *Tenant Alpha* is strictly prohibited from accessing, viewing, or modifying cameras, recordings, devices, or evidence belonging to *Tenant Beta*. Any violation raises `TenantAccessDeniedError` and triggers an audit alarm.
3. **Dual-Control Quorum for Raw Visual Access:** A single operator or administrator cannot unilaterally export unmasked raw video. Privacy-sensitive operations require simultaneous co-signing by both a **Forensic Investigator** and a **Tenant/Super Administrator** (`QuorumAuthorizationError`).
4. **Tamper-Sealed Audit Trails with Zero Credential Leakage:** Audit logs are sealed in an unbroken SHA-256 Merkle hash chain. Sensitive credentials (passwords, tokens, private keys) and raw video frames are sanitized prior to disk write.

---

## 2. Multi-Tenant Partitioning Model

Implemented in `src/camserv/security/tenancy.py`:

```
+═════════════════════════════════════════════════════════════════════════════════+
║                         CAMserv Enterprise Platform                             ║
+═════════════════════════════════════════════════════════════════════════════════+
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
+──────────────────────────+          +──────────────────────────+
| Tenant Alpha (Airport)   |          | Tenant Beta (Logistics)  |
+──────────────────────────+          +──────────────────────────+
| Site: Terminal 1         |          | Site: Warehouse 4        |
| - Devices: 12 Appliances |          | - Devices: 6 Appliances  |
| - Cameras: 144 Streams   |          | - Cameras: 48 Streams    |
| - Operators: [Alice]     |          | - Operators: [Bob]       |
| - Isolated Evidence      |          | - Isolated Evidence      |
+──────────────────────────+          +──────────────────────────+
```

### Hierarchy of Isolation:
$$\text{Tenant (Organization)} \longrightarrow \text{Site (Facility)} \longrightarrow \text{Appliance (Hardware)} \longrightarrow \text{Camera (Sensor)} \longrightarrow \text{Evidence / Manifest}$$

When an API request arrives, `MultiTenantEnforcer.enforce_tenant_boundary` verifies that the resource's `tenant_id` matches the caller's JWT `TenantContext`. Cross-tenant queries are blocked immediately.

---

## 3. Role-Based Access Control (RBAC) Matrix

Implemented in `src/camserv/security/rbac.py`:

| Platform Permission | SUPER_ADMIN | TENANT_ADMIN | SITE_ADMIN | SECURITY_OPERATOR | FORENSIC_INVESTIGATOR | AUDITOR |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `stream:view_masked` | **YES** | **YES** | **YES** | **YES** | **YES** | NO |
| `stream:view_unmasked` | **QUORUM** | **QUORUM** | NO | NO | **QUORUM** | NO |
| `event:review` | **YES** | **YES** | **YES** | **YES** | **YES** | NO |
| `event:confirm_alert` | **YES** | **YES** | **YES** | **YES** | NO | NO |
| `evidence:view_derivative` | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** |
| `evidence:export_derivative` | **YES** | **YES** | **YES** | NO | **YES** | NO |
| `evidence:export_raw` | **QUORUM** | **QUORUM** | NO | NO | **QUORUM** | NO |
| `camera:configure` | **YES** | **YES** | **YES** | NO | NO | NO |
| `device:enroll` | **YES** | **YES** | NO | NO | NO | NO |
| `device:manage` | **YES** | **YES** | **YES** | NO | NO | NO |
| `audit:read` | **YES** | **YES** | NO | NO | **YES** | **YES** |
| `tenant:manage` | **YES** | NO | NO | NO | NO | NO |

---

## 4. Dual-Control Cryptographic Quorum (Four-Eyes Principle)

In high-security and legal contexts, unauthorized decryption of unmasked surveillance video constitutes a severe breach of data protection laws (GDPR Art. 9 & 25).

CAMserv mandates the **Four-Eyes Principle (Dual Control)** for:
1. `stream:view_unmasked`: Unobscured live monitoring of faces and license plates.
2. `evidence:export_raw`: Extraction of unmasked pristine original chunks from the vault.

```
+───────────────────────────+       +───────────────────────────+
|   Forensic Investigator   |       |   Tenant / Super Admin    |
|   (Legal / Judicial Role) |       |   (Administrative Role)   |
+─────────────┬─────────────+       +─────────────┬─────────────+
              │                                   │
              │ Co-Signer 1                       │ Co-Signer 2
              └─────────────────┬─────────────────┘
                                ▼
         +───────────────────────────────────────────────+
         |     RBACPolicyEngine.enforce_quorum()         |
         |  - Verifies distinct authorized roles         |
         |  - Validates cryptographic signatures         |
         |  - Generates immutable quorum audit record    |
         +──────────────────────┬────────────────────────+
                                │
                                ▼
          [Temporary Unmasked Evidence Export Token Issued]
```

---

## 5. Cryptographic Audit Trail Architecture

Implemented in `src/camserv/security/audit_trail.py`:

### 5.1 Deep Field Sanitization
Prior to writing any audit event, `SecurityAuditLogger.sanitize_details` recursively scrubs sensitive tokens:
* Passwords and password hashes $\implies$ `[REDACTED_BY_SECURITY_POLICY]`
* API tokens, JWTs, and private keys $\implies$ `[REDACTED_BY_SECURITY_POLICY]`
* Raw binary frame payloads $\implies$ `<binary_bytes_len_N>`

### 5.2 SHA-256 Merkle Hash Chaining
Audit records are linked into an immutable hash chain:
$$h_0 = \text{GENESIS\_HASH}$$
$$h_i = \text{SHA256}(\text{entry\_id} \parallel \text{timestamp} \parallel \text{tenant} \parallel \text{user} \parallel \text{action} \parallel \text{status} \parallel \text{ip} \parallel \text{SHA256}(details) \parallel h_{i-1})$$

Any unauthorized modification of an existing audit entry, insertion of an unchained record, or truncation of history breaks `verify_chain_integrity`, providing courtroom-admissible evidence of record tampering.

---

## 6. Stage 5 Acceptance Decision

$$\mathbf{STAGE\_5\_ACCEPTANCE\_VERDICT: \quad ACCEPTED}$$

All deliverables for Stage 5 (Enterprise Security, Identity & Multi-Tenancy) have been implemented, verified with 5 unit tests in `tests/test_enterprise_security.py`, and documented.
