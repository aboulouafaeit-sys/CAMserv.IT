# CAMserv — Phase 26: Authorization Matrix & Access Control
## Zero-Trust Object-Level Scoping, RBAC Matrix & AAL Enforcement

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26 — Identity & Access Security Foundation  
**Framework:** Role-Based Access Control (RBAC) + Object-Level Access Control (OLAC)  
**Author:** Principal Security Architect  
**Status:** COMPLETE & VERIFIED  

---

## 1. Zero-Trust Access Model & Evaluation Pipeline

CAMserv enforces a dual-layered authorization model:
1. **Layer 1: Role Capability Evaluation (RBAC):** Checks whether the caller's role possesses the broad capability to perform the action.
2. **Layer 2: Object-Level Scope Evaluation (OLAC):** Checks whether the caller has explicit assignment to the requested asset ID (preventing horizontal BOLA/IDOR privilege escalation).
3. **Layer 3: Authentication Assurance Level (AAL) Verification:** Verifies whether the caller's session meets the minimum NIST SP 800-63B assurance level (AAL2 multi-factor verification required for sensitive or destructive operations).

```mermaid
flowchart TD
    Req["Incoming API Request\n(user_id, action, resource_type, resource_id, session)"]
    CheckActive{"1. Is account active\n& not locked?"}
    CheckSession{"2. Is session active\n& not revoked/expired?"}
    CheckAAL{"3. Does action require AAL2?\nDoes session meet requirement?"}
    CheckScope{"4. Does user have explicit\nResourceScope or Camera Assignment?"}
    CheckRole{"5. Does Role permit\naction pattern?"}
    Allow["GRANT ACCESS (200 OK)"]
    Deny["DENY ACCESS (403 Forbidden)"]
    DenyBOLA["DENY & ALERT SENTINEL\n(BOLA Violation Recorded)"]
    StepUp["DENY WITH STEP-UP PROMPT\n(401 / 403 AAL2 Required)"]

    Req --> CheckActive
    CheckActive -->|No| Deny
    CheckActive -->|Yes| CheckSession
    CheckSession -->|No| Deny
    CheckSession -->|Yes| CheckAAL
    CheckAAL -->|Fails AAL2| StepUp
    CheckAAL -->|Satisfied| CheckScope
    CheckScope -->|Scope Matched| Allow
    CheckScope -->|No Scope| CheckRole
    CheckRole -->|Role Not Permitted| Deny
    CheckRole -->|Role Permitted| CheckCameraObj{"Is resource a camera/stream/rec?\nIs camera in user's allowed set?"}
    CheckCameraObj -->|No (Unassigned Asset)| DenyBOLA
    CheckCameraObj -->|Yes (Assigned)| Allow
```

---

## 2. Role Permission Matrix

| Permission Name | Category | ADMIN | OPERATOR | VIEWER | AUDITOR | Minimum AAL | Description |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `camera:view` | Surveillance | ✅ | ✅ | ✅ | ✅ | AAL1 | View live RTSP / WebRTC camera video |
| `camera:ptz` | Control | ✅ | ✅ | ❌ | ❌ | AAL1 | Pan/Tilt/Zoom physical camera control |
| `stream:view` | Surveillance | ✅ | ✅ | ✅ | ✅ | AAL1 | Access low-latency sub-streams |
| `recording:view` | Playback | ✅ | ✅ | ✅ | ✅ | AAL1 | View recording timeline metadata |
| `recording:playback` | Playback | ✅ | ✅ | ✅ | ✅ | AAL1 | Playback historical video segments |
| `recording:delete` | Maintenance | ✅ | ❌ | ❌ | ❌ | **AAL2** | Delete recorded video segments |
| `event:view` | Analytics | ✅ | ✅ | ✅ | ✅ | AAL1 | Inspect analytics and motion events |
| `event:acknowledge` | Operations | ✅ | ✅ | ❌ | ❌ | AAL1 | Acknowledge active alarms / alerts |
| `evidence:view` | Forensics | ✅ | ❌ | ❌ | ✅ | AAL1 | Inspect judicial vault case records |
| `evidence:export` | Forensics | ✅ | ❌ | ❌ | ❌ | **AAL2** | Export signed ZIP / MP4 court evidence |
| `evidence:hold` | Forensics | ✅ | ❌ | ❌ | ❌ | **AAL2** | Place preservation hold on footage |
| `evidence:release` | Forensics | ✅ | ❌ | ❌ | ❌ | **AAL2** | Release preservation hold on footage |
| `audit:view` | Governance | ✅ | ❌ | ❌ | ✅ | AAL1 | Inspect cryptographic security event log |
| `audit:export` | Governance | ✅ | ❌ | ❌ | ✅ | **AAL2** | Export signed JSONL audit ledger |
| `account:create` | Security | ✅ | ❌ | ❌ | ❌ | **AAL2** | Register new local user accounts |
| `account:delete` | Security | ✅ | ❌ | ❌ | ❌ | **AAL2** | Delete local user accounts |
| `account:modify_role` | Security | ✅ | ❌ | ❌ | ❌ | **AAL2** | Promote or demote user roles |
| `system:status` | Health | ✅ | ✅ | ❌ | ✅ | AAL1 | View CPU, RAM, GPU, storage telemetry |
| `system:config` | Maintenance | ✅ | ❌ | ❌ | ❌ | **AAL2** | Alter appliance network or storage paths |
| `system:shutdown` | Maintenance | ✅ | ❌ | ❌ | ❌ | **AAL2** | Appliance reboot or controlled shutdown |

---

## 3. Object-Level Scoping & BOLA/IDOR Prevention

### 3.1 Individual Client Scoping Rules
- Each `UserRecord` contains `allowed_camera_ids: set[str]`.
- For clients with role `VIEWER` or `OPERATOR`:
  - Access to `camera:view`, `stream:view`, or `recording:playback` checks if `target_camera_id in user.allowed_camera_ids`.
  - If a user attempts to request video from `cam_secure_vault` and their profile only allows `cam_lobby`, access is **strictly denied**.
  - Repeated unauthorized object access triggers CAMserv Sentinel horizontal scanning mitigation (`SENTINEL_BOLA_PROBING_DETECTED`), immediately terminating the attacker's active session.

### 3.2 Granular Resource Scope Delegation
Administrators can grant explicit, temporary, or surgical permissions using `ResourceScope` records without altering the user's primary role:
- Scope record contains: `scope_id`, `user_id`, `resource_type`, `resource_id`, `permissions`, `granted_by`.
- Example: Granting an auditor temporary `evidence:view` access to specific case ID `case_2026_09` only.
- Scopes take precedence over baseline role restrictions, enabling flexible zero-trust delegation while maintaining auditability.
