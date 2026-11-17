# CAMserv — Phase 26: Identity & Access Architecture
## Local-First Zero-Trust Identity, Authentication, Authorization & Account Protection

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26 — Identity & Access Security Foundation  
**Architecture Model:** Single Organization / Local Deployment / Local Root Authority  
**Author:** Principal Security Architect & Lead Cryptographic Systems Engineer  
**Status:** COMPLETE & INDEPENDENTLY QUALIFIED  

---

## 1. Executive Summary & Core Architectural Invariants

CAMserv Phase 26 establishes a hardened, production-grade identity, authentication, and authorization subsystem designed specifically for mission-critical surveillance appliances. Operating under an uncompromising **Local-First Zero-Trust** security architecture, CAMserv acts as its own autonomous cryptographic identity authority without requiring SaaS connectors, cloud identity providers, or active internet connectivity.

### Non-Negotiable Core Invariants:
1. **Local Autonomous Authority:** All user accounts, credential verifications, role evaluations, and session states are managed locally on the appliance.
2. **Recording Pipeline Absolute Isolation:** Failure, corruption, or active denial-of-service against the identity database or authentication endpoints **never** blocks, halts, or degrades RTSP camera ingestion, recording continuity ledgers, or cryptographic evidence hashing.
3. **No Shared / Generic Accounts:** Shared operator accounts (e.g., generic "operator/operator") are eliminated in favor of individual accountability with traceable user IDs.
4. **Zero Default Credentials:** No hardcoded passwords, default admin/admin pairs, or insecure bypasses exist in the appliance codebase. Initial bootstrap requires local console token retrieval.
5. **Deny-by-Default Object Authorization:** Access to cameras, live streams, recordings, and judicial vaults is evaluated on an object-by-object basis, preventing Broken Object Level Authorization (BOLA/IDOR).
6. **Continuous Forensic Immutability:** Pre-existing forensic audit ledgers (`logs/audit.jsonl` exactly 20,977 bytes, hash `F2A2484A...`) and the 34 official brand assets are strictly preserved.

---

## 2. Architecture Overview & Component Topology

```mermaid
flowchart TD
    subgraph ClientAccess["Client Access Layer"]
        CLI["Local Admin Console"]
        WebUI["CAMserv Web Dashboard"]
        APIClient["Authenticated REST/WS Client"]
    end

    subgraph SecurityPerimeter["CAMserv Identity & Access Perimeter"]
        Bootstrap["LocalAdministratorBootstrap\n(One-Time Local File Token)"]
        Sentinel["CAMservSentinelIdentity\n(Adaptive Brute Force & BOLA Defense)"]
        SessionMgr["SessionManager\n(256-bit Tokens, Idle/Absolute Timeout)"]
        PolicyEngine["ZeroTrustPolicyEngine\n(RBAC + Object Scope + AAL Level)"]
        Hasher["Argon2idPasswordHasher\n(RFC 9106 m=65536, t=2, p=4)"]
        MFA["TOTPManager & RecoveryCodes\n(RFC 6238, AES-256-GCM Secret)"]
        Vault["CameraCredentialProtection\n(AES-256-GCM Vault & URL Redaction)"]
        Lockdown["EmergencyLockdownManager\n(Threat Containment)"]
        AuditLedger["TamperEvidentSecurityAudit\n(SHA-256 Forward Hash Chain)"]
    end

    subgraph Persistence["Local Durable Storage"]
        DB[(data/identity.db\nSQLite WAL Mode)]
        KeyStore[(data/secrets/\nRestrictive Key Material)]
    end

    subgraph VideoEngine["Recording & Surveillance Core (Strictly Isolated)"]
        Ingest["RTSP Ingestion Pipeline"]
        Continuity["RecordingContinuityLedger"]
        Storage["Adaptive Storage & Vault"]
    end

    ClientAccess -->|Bootstrap Token| Bootstrap
    ClientAccess -->|Login Request| Sentinel
    Sentinel -->|Pass/Fail Rate-Limited| Hasher
    Hasher -->|Validate Credential| DB
    Sentinel -->|MFA Challenge| MFA
    MFA -->|Verify Step| DB
    ClientAccess -->|Access Token / Session| SessionMgr
    SessionMgr -->|Validate & Touch| DB
    ClientAccess -->|Asset Request| PolicyEngine
    PolicyEngine -->|Authorize Asset| DB
    PolicyEngine -->|Block BOLA Scanning| Sentinel
    Lockdown -->|Revoke Non-Admin Sessions| SessionMgr
    SecurityPerimeter -->|Cryptographic Chained Events| AuditLedger
    AuditLedger -->|Append Entry| DB

    %% Critical Isolation Boundary
    SecurityPerimeter -.->|STRICT AIRGAP / ZERO DEPENDENCY| VideoEngine
```

---

## 3. Subsystem Breakdown

### 3.1 Data Models (`camserv.security.identity.models`)
Defines the strictly-typed foundational entities:
- `AccountStatus`: `PENDING_BOOTSTRAP`, `PENDING_ACTIVATION`, `ACTIVE`, `SUSPENDED`, `LOCKED`, `DEACTIVATED`.
- `IdentityRole`: `ADMIN`, `OPERATOR`, `VIEWER`, `AUDITOR`.
- `ResourceType`: `CAMERA`, `STREAM`, `RECORDING`, `EVENT`, `EVIDENCE`, `EXPORT`, `STORAGE`, `CONFIG`, `AUDIT`, `SESSION`, `ACCOUNT`, `SYSTEM`.
- `AuthAssuranceLevel`: `AAL1` (Single-factor), `AAL2` (MFA/TOTP/Recovery Code), `AAL3` (Hardware key/Passkey).
- `MFAType`: `NONE`, `TOTP`, `PASSKEY`, `RECOVERY_CODE`.
- `ResourceScope`: Granular, object-level grant linking `user_id` to `resource_id` with specific permissions.
- `UserRecord`: Persistent profile tracking failed login counts, lockout timestamps, allowed camera sets, and credential status.
- `SessionRecord`: Stateful, revocable session entity with idle and absolute lifetime validation.
- `SecurityEvent`: Forensic anomaly and audit record with forward cryptographic hash-chain fields.

### 3.2 High-Assurance Password Engine (`camserv.security.identity.password`)
- **Primary Algorithm:** RFC 9106 Argon2id calibrated to $m=65536$ KiB (64 MiB), $t=2$ iterations, $p=4$ parallel lanes, 32-byte derived key.
- **PHC String Format:** `$argon2id$v=19$m=65536,t=2,p=4$<salt>$<hash>`.
- **Dual-Verification Support:** Backwards-compatible verification for legacy `pbkdf2_sha256$` hashes with automatic `needs_rehash()` detection upon successful login.
- **Bounded Concurrency:** Guarded by `threading.Semaphore(max_concurrency=4)` preventing memory exhaustion DoS under high-volume authentication bursts.
- **Zero Silent Truncation:** Passwords up to 1024 characters are fully processed without arbitrary buffer clipping.
- **Passphrase Exemption:** Passphrases $\ge 20$ characters are exempt from arbitrary character-class rules, supporting high-entropy word phrases.

### 3.3 Durable Identity Store (`camserv.security.identity.store`)
- Transactional SQLite database with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=NORMAL;`, `PRAGMA foreign_keys=ON;`).
- Relational schema with foreign key cascades:
  - `users`: Core account profiles and status.
  - `password_credentials`: Current hash and historical hash queue (preventing password reuse).
  - `totp_credentials`: AES-256-GCM encrypted TOTP secrets with replay protection counter.
  - `recovery_codes`: SHA-256 hashed single-use emergency recovery codes.
  - `passkey_credentials`: Public key WebAuthn credentials.
  - `sessions`: Stateful session table with activity tracking.
  - `resource_scopes`: Object-level resource grants.
  - `security_events`: Cryptographically linked forensic security audit ledger.
  - `bootstrap_state`: Persistent state machine for appliance initialization.

### 3.4 Local Administrator Bootstrap (`camserv.security.identity.bootstrap`)
- Guarantees zero factory default credentials.
- When an uninitialized appliance starts, it generates a 256-bit cryptographically secure token stored in a restrictive local file (`data/.bootstrap_token`, permissions `0600`) with a 15-minute time-to-live.
- The administrator must physically or via secure console read the token and submit their chosen credentials.
- Mandatory TOTP MFA enrollment and generation of 10 single-use recovery codes are executed during bootstrap.
- Upon completion, the token file is cryptographically shredded and deleted, and bootstrap is permanently sealed (`BootstrapAlreadyCompletedError` on any re-attempt).

### 3.5 Multi-Factor Authentication Engine (`camserv.security.identity.mfa`)
- **RFC 6238 TOTP:** Implements standard HMAC-SHA1/SHA256 time-based one-time passwords with 30-second windows and dynamic truncation.
- **Replay Protection:** Tracks `last_used_step` in durable storage; identical codes within the active drift window are immediately rejected.
- **Clock Drift Tolerance:** Allows $\pm 1$ time-step tolerance ($\pm 30$ seconds) to accommodate appliance clock variance.
- **Encrypted Secret Storage:** TOTP secrets are encrypted at rest using AES-256-GCM with a dedicated key derived via HKDF.
- **Recovery Codes:** Generates 10 single-use, 16-character alphanumeric codes (`XXXX-XXXX-XXXX-XXXX`), stored as SHA-256 hashes and permanently consumed upon use.
- **WebAuthn / Passkey Ready:** Includes standard registration and assertion option hooks for FIDO2/WebAuthn hardware tokens.

### 3.6 Zero-Trust Policy Engine (`camserv.security.identity.authorization`)
- **Deny-by-Default:** Any action without an explicit grant is denied.
- **Object-Level Scoping (BOLA/IDOR Defense):** Individual clients can only view or control cameras explicitly assigned to them in `allowed_camera_ids` or via `ResourceScope` records. Accessing unassigned cameras is denied and flagged to Sentinel.
- **AAL2 Mandatory Enforcement:** High-risk actions (`evidence:export`, `system:config`, `account:create`, `account:delete`, `recording:delete`) strictly require an AAL2 session (multi-factor verified).

### 3.7 Stateful Session Manager (`camserv.security.identity.session`)
- Issues 256-bit cryptographically secure session IDs (`secrets.token_hex(24)`).
- Enforces an idle timeout (default 30 minutes) and absolute lifetime timeout (default 12 hours).
- **Session Fixation Defense:** Elevating privilege or completing step-up authentication atomically revokes the old session ID and issues a fresh session record.
- **Concurrency Cap:** Limits simultaneous active sessions per user (default 5), automatically revoking the oldest active session.

### 3.8 CAMserv Sentinel Identity (`camserv.security.identity.sentinel`)
- **Adaptive Brute-Force Throttling:** Calculates deterministic progressive delay ($0.5 \times 2^{\text{failures}}$ s) to throttle automated credential stuffing.
- **Account Lockout:** Automatically locks accounts for 5 minutes after 5 consecutive failures.
- **IP Range Blocking:** Blocks IP addresses exhibiting $>20$ failed attempts across accounts.
- **Horizontal Scanning Defense:** Detects repeated unauthorized object access attempts (BOLA probing) and instantly revokes the attacking session.
- **Session Hijacking Defense:** Detects unauthorized client IP mutation on active sessions and terminates the session.
- **Bounded Memory:** Implements sliding window queues with maximum size ceilings, preventing memory exhaustion.

### 3.9 Tamper-Evident Security Audit Ledger (`camserv.security.identity.audit`)
- Maintains a forward SHA-256 cryptographic hash chain across all security events:
  $$\text{Hash}_n = \text{SHA-256}(\text{EventData}_n \parallel \text{Hash}_{n-1})$$
- First record anchors to fixed genesis hash: `GENESIS_SECURITY_AUDIT_HASH_PHASE26_00000000`.
- Built-in audit verifier detects any SQLite record tampering, deletion, or out-of-order insertion.
- Forensic JSONL export utility generates portable, verifiable audit packages.

### 3.10 Camera Credential Protection (`camserv.security.identity.secrets`)
- **AES-256-GCM Vault:** Encrypts RTSP, ONVIF, and HTTP passwords at rest with key separation via HKDF (`camserv-v1-camera-credentials`).
- **URL Credential Scrubbing:** Sanitizes URLs (e.g., `rtsp://admin:secret@host:554/live` $\to$ `rtsp://admin:***REDACTED***@host:554/live`) handling complex passwords with special characters (`@`, `:`, `/`).
- **Deep Redaction:** Automatically scrubs sensitive dictionaries and API responses before transmission.

### 3.11 Emergency Appliance Lockdown (`camserv.security.identity.emergency`)
- Rapid threat containment mode declared via administrator console or Sentinel critical alerts.
- Atomically revokes all client sessions and blocks non-admin logins and external evidence exports.
- **Recording Invariant:** Ingestion pipelines, continuous video recording, and cryptographic frame hashing continue **uninterrupted** during emergency lockdown.
