# CAMserv — Phase 26.1: Authorization Verification & BOLA/IDOR Penetration Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26.1 — Identity Security Verification & Adversarial Hardening  
**Scope:** Zero-Trust Authorization Engine, BOLA/IDOR Protection & NIST SP 800-63B AAL Verification  
**Audit Role:** Principal Application Security Engineer & Penetration Testing Authority  
**Status:** PASS — VERIFIED IN HARDENED CODE & ADVERSARIAL SUITE  

---

## 1. Executive Summary

As part of the independent adversarial qualification of CAMserv Phase 26.1, the authorization layer (`ZeroTrustPolicyEngine` in `src/camserv/security/identity/authorization.py`) was subjected to targeted penetration testing against common API and web application vulnerability classes:
- Broken Object Level Authorization (OWASP API1:2023 - BOLA / IDOR).
- Horizontal Privilege Escalation (inter-client data leaks).
- Vertical Privilege Escalation (unprivileged viewer/operator attempting administrative operations).
- Direct UI-Bypass Attacks (crafted HTTP/RPC payloads bypassing frontend controls).
- NIST SP 800-63B Authentication Assurance Level (AAL) enforcement.

Every test executed against the production policy engine confirmed that CAMserv strictly enforces **deny-by-default, object-level access controls** directly at the domain and service layers, completely independent of frontend UI state.

---

## 2. Comprehensive Endpoint-to-Authorization Matrix

The following matrix documents the exact permissions, required roles, required Authentication Assurance Levels (AAL), and object-level scoping rules enforced across CAMserv:

| Endpoint / Operation | Primary Resource Type | Required Action Permission | Minimum Role | Required AAL | Object-Level Scope Enforcement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /api/v1/cameras` | `ResourceType.CAMERA` | `camera:list` | `VIEWER` | AAL1 | Filtered to explicitly allowed camera IDs. |
| `GET /api/v1/cameras/{id}/live` | `ResourceType.STREAM` | `camera:view` | `VIEWER` | AAL1 | Strict ID check against `user.allowed_camera_ids`. |
| `POST /api/v1/cameras/{id}/ptz` | `ResourceType.CAMERA` | `camera:ptz` | `OPERATOR` | AAL1 | Scoped to assigned camera; blocked for VIEWER. |
| `PUT /api/v1/cameras/{id}/config`| `ResourceType.CONFIG` | `camera:configure` | `ADMIN` | AAL2 | Blocked for all non-admins; requires step-up MFA. |
| `GET /api/v1/recordings` | `ResourceType.RECORDING` | `recording:list` | `VIEWER` | AAL1 | Filtered to recordings of allowed cameras only. |
| `GET /api/v1/recordings/{id}` | `ResourceType.RECORDING` | `recording:playback` | `VIEWER` | AAL1 | Validates associated camera ownership. |
| `POST /api/v1/evidence/export` | `ResourceType.EVIDENCE` | `evidence:export` | `OPERATOR` | AAL2 | High-impact action; mandatory step-up challenge. |
| `POST /api/v1/evidence/hold` | `ResourceType.EVIDENCE` | `preservation:create` | `ADMIN` | AAL2 | Mandatory step-up challenge and audit signature. |
| `GET /api/v1/system/status` | `ResourceType.SYSTEM` | `system:status` | `VIEWER` | AAL1 | Sanitized diagnostic telemetry only. |
| `POST /api/v1/system/update` | `ResourceType.SYSTEM` | `system:firmware_update`| `ADMIN` | AAL2 | Appliance firmware installation; requires AAL2. |
| `POST /api/v1/emergency/lockdown`| `ResourceType.SYSTEM`| `emergency:declare` | `OPERATOR` | AAL1 | Failsafe containment allowed rapidly. |
| `POST /api/v1/emergency/lift` | `ResourceType.SYSTEM` | `emergency:lift` | `ADMIN` | AAL2 | Unprivileged lifting strictly blocked. |

---

## 3. BOLA / IDOR Penetration Testing Results

### 3.1 Attack Scenario: Direct Camera Object Substitution
An adversary authenticated as an unprivileged client (`lobby_guard`) with permissions strictly limited to the front lobby camera (`cam_lobby`) attempts to query live RTSP streams and recordings for the executive vault camera (`cam_vault`):

```python
# Adversary Session Context:
user = UserRecord(
    user_id="usr_op_lobby",
    username="lobby_guard",
    role=IdentityRole.OPERATOR,
    allowed_camera_ids={"cam_lobby"}
)

# Adversarial Request:
decision = policy_engine.authorize(
    user=user,
    action="camera:view",
    resource_type=ResourceType.CAMERA,
    resource_id="cam_vault"
)
```

**Outcome:**
- `decision.allowed == False`
- `decision.reason == "Access denied: user is not assigned to resource 'cam_vault' (BOLA prevention)"`
- `decision.matched_scope_id == None`

**Verdict:** **BLOCKED & LOGGED**. The engine evaluates object ownership before evaluating action verbs.

### 3.2 Automated Sentinel BOLA Scanning Correlation
When an adversary rapidly iterates through camera IDs (e.g., `cam_01`, `cam_02`, `cam_03`, `cam_vault`), `CAMservSentinelIdentity.record_authorization_violation` tracks unauthorized attempts in a sliding memory window.
- Upon 3 unauthorized resource requests within the window:
  - Sentinel immediately revokes the attacker's active session (`session.is_revoked = True`).
  - Emits a `SecurityEvent` of severity `CRITICAL` with type `SENTINEL_BOLA_PROBING_DETECTED`.
  - All subsequent requests with that session token are rejected with `SessionRevokedError`.

---

## 4. Privilege Escalation Penetration Testing

### 4.1 Vertical Privilege Escalation (Viewer to Administrator)
- **Vector 1: PTZ Camera Manipulation:**
  - An attacker possessing a `VIEWER` role submits raw REST calls to `/api/v1/cameras/{id}/ptz`.
  - Result: `decision.allowed == False`, `reason == "Role 'viewer' does not permit action 'camera:ptz'"`.
- **Vector 2: Camera Configuration Modification:**
  - An attacker possessing an `OPERATOR` role attempts to alter RTSP streaming endpoints or camera credentials.
  - Result: `decision.allowed == False`, `reason == "Role 'operator' does not permit action 'camera:configure'"`.
- **Vector 3: Role Modification Tampering:**
  - An attacker injects `{"role": "admin"}` in their user profile update payload.
  - Result: The user profile update handler rejects role assignment unless the executing session possesses `system:admin` permissions at `AAL2`.

---

## 5. NIST SP 800-63B Authentication Assurance Level (AAL) Verification

NIST SP 800-63B defines explicit guidelines for multi-factor authentication assurance:
- **AAL1:** Single-factor authentication (e.g., password only).
- **AAL2:** Multi-factor authentication with proof of possession of a separate cryptographic key or secret (Argon2id password + TOTP / recovery code).
- **AAL3:** Hardware-backed cryptographic authenticator (WebAuthn/FIDO2 hardware key).

### Mandatory AAL2 Operation Verification
In CAMserv, high-impact operations are cataloged in `AAL2_MANDATORY_PERMISSIONS`:
```python
AAL2_MANDATORY_PERMISSIONS = frozenset({
    "system:firmware_update",
    "system:factory_reset",
    "system:restore_backup",
    "account:delete",
    "account:role_change",
    "camera:credentials_export",
    "evidence:export",
    "evidence:delete",
    "audit:export",
    "emergency:lift",
})
```

**Adversarial Test Result:**
- An authenticated administrator possessing an active `AAL1` session (e.g., logged in via username and password, but without completing TOTP step-up) attempted to invoke `evidence:export` and `system:firmware_update`.
- In every case, `ZeroTrustPolicyEngine.authorize()` returned `allowed = False` with `required_aal = AuthAssuranceLevel.AAL2` and `reason = "Action requires multi-factor authentication (AAL2)"`.
- Once step-up authentication was completed (session upgraded to `AAL2`), identical requests evaluated to `allowed = True`.

---

## 6. UI-Bypass Penetration Verification

CAMserv's client-side web application features a responsive control pane that visually disables controls unassigned to the current user role. To prove that security does not rely on frontend masking:
1. Direct raw HTTP requests were dispatched directly to the service layer with handcrafted JSON payloads.
2. The frontend masking layer was completely removed from the test execution harness.
3. Every request evaluated identically through the backend `ZeroTrustPolicyEngine`.
4. No request lacking cryptographic session authorization succeeded.

---

## 7. Audit Conclusion

The CAMserv Phase 26.1 authorization architecture provides robust, defense-in-depth protection:
- **BOLA / IDOR:** Fully mitigated via strict object-level validation.
- **Horizontal Scanning:** Mitigated via Sentinel anomaly correlation and automatic session revocation.
- **Vertical Escalation:** Strictly prevented by role-matrix enforcement.
- **Critical Action Protection:** Enforced via NIST SP 800-63B AAL2 step-up challenges.
- **Frontend Independence:** 100% backend enforced.
