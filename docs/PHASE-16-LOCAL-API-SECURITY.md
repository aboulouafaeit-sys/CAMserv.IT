# Phase 16: Local API Security & Inter-Process Authentication

**Target Release:** 0.10.0-alpha2  
**Evaluated Subject:** REST Endpoints, WebSocket Streams, JWT Tokens, Loopback Security  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Executive Summary

Because the Desktop Operator Console and external integrations communicate with the CAMserv background Windows Service via HTTP/WebSocket, robust authentication and authorization controls are mandatory to protect video feeds and camera configurations.

---

## 2. API Security Architecture

```
+-----------------------------------+
|  Desktop Console / Web Browser    |
+-----------------------------------+
                  |
     1. POST /api/v1/auth/token
        (Credentials: Username + Password)
                  |
                  v
+-----------------------------------+
|     JWT Authentication Provider   |
|  - Validates Argon2id / bcrypt    |
|  - Generates Signed JWT (HS256)   |
|  - Embeds Role & Expiration       |
+-----------------------------------+
                  |
     2. Returns Bearer Access Token
                  |
                  v
+-----------------------------------+
|   Protected Endpoints (RBAC)      |
|  - /api/v1/cameras                |
|  - /api/v1/recordings             |
|  - /api/v1/events                 |
|  - /api/v1/forensics              |
+-----------------------------------+
```

---

## 3. Security Controls & Protections

1. **JWT Bearer Token Enforcement:**
   Protected endpoints require `Authorization: Bearer <token>`. Unauthenticated requests immediately receive HTTP `401 Unauthorized`.
2. **Loopback Binding by Default:**
   The service listens on `127.0.0.1:8080` by default. Binding to `0.0.0.0` is strictly opt-in and requires explicit administrator confirmation.
3. **Role-Based Access Control (RBAC):**
   Three role tiers: `ADMIN`, `OPERATOR`, `VIEWER`.
   - `VIEWER`: Read-only access to live feeds.
   - `OPERATOR`: Live feeds, playback, and incident acknowledgement.
   - `ADMIN`: Camera addition/deletion, certificate rotation, and service reconfiguration.
4. **Rate Limiting & Anti-Brute-Force:**
   Failed authentication attempts trigger exponential backoff delays and audit log recording.

---

## 4. Verification Evidence

- **Unit Test:** `test_desktop_client_unauthenticated_and_offline` — PASSED.
- **Unit Test:** `test_desktop_client_mock_api_interaction` — PASSED.
- All 328 automated tests passing.
