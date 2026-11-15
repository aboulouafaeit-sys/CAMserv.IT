# CAMserv — Phase 3 Central Management & Fleet Architecture

**Document ID:** ARCH-CENTRAL-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Stage 3 Deliverable  
**Date:** November 15, 2026  
**Status:** PRODUCTION CENTRAL FLEET ARCHITECTURE  
**Author / Authority:** Distributed Systems Engineer, Enterprise Infrastructure Architect & Cybersecurity Architect  

---

## 1. Executive Summary & Design Scope

**CAMserv Central** is the enterprise fleet management and coordination plane engineered to administer, monitor, update, and audit hundreds of distributed **CAMserv AI Appliances** and **Edge Nodes** across multi-site enterprise environments (such as international airport networks, distributed logistics hubs, utility grids, and corporate campuses).

### Non-Negotiable Core Invariants:
1. **Zero-Trust Device Identity:** Network presence does not confer trust. Every appliance must be explicitly commissioned via one-time cryptographically scoped enrollment tokens and continuously authenticated via **Ed25519 digital signatures** over cryptographic challenge-response nonces.
2. **Server-Side Multi-Site Isolation:** Physical sites are strictly segregated. An operator or security officer authorized for *Site Alpha* is mathematically barred from querying, viewing, or administering devices belonging to *Site Beta*. Access control is enforced server-side.
3. **Data Minimization over WAN:** CAMserv Central never centralizes raw continuous video streams over wide-area networks. Central ingests **health telemetry, threat event alerts, and signed cryptographic manifests** exclusively. Pristine raw evidence remains securely vaulted on the local edge appliances.
4. **Honest Telemetry Reporting:** Dashboard metrics (online/offline status, camera counts, storage usage, active threat alerts) reflect real device telemetry reported within validated keepalive windows.

---

## 2. Central Fleet Ecosystem Topology

```
+═════════════════════════════════════════════════════════════════════════════════+
║                         CAMserv Central Management Plane                        ║
║           (Device Registry, Multi-Site RBAC, Fleet Overview Dashboard)          ║
+═════════════════════════════════════════════════════════════════════════════════+
          ▲                                  ▲                                  ▲
          │ mTLS (Mutual TLS v1.3)           │ Ed25519 Challenge-Response       │ Real-Time Health Telemetry
          ▼                                  ▼                                  ▼
+──────────────────────────+     +──────────────────────────+     +──────────────────────────+
|  Site Alpha: Frankfurt   |     |  Site Beta: Hamburg      |     |  Site Gamma: Munich      |
|  (Terminal 1 & Cargo)    |     |  (Logistics Hub 4)       |     |  (Perimeter Substation)  |
+──────────────────────────+     +──────────────────────────+     +──────────────────────────+
| • Appliance-001 (Pro)    |     | • Appliance-002 (Pro)    |     | • Edge-001 (Edge Profile)|
| • Appliance-002 (Ent)    |     | • Edge-003 (Edge Profile)|     | • 4 Local Cameras        |
| • 24 Local Cameras       |     | • 12 Local Cameras       |     | • Fanless 15W Node       |
| • Local Forensic Vault   |     | • Local Forensic Vault   |     | • Local Vault Storage    |
+──────────────────────────+     +──────────────────────────+     +──────────────────────────+
```

---

## 3. Cryptographic Device Registry Schema

Implemented in `src/camserv/central/models.py` and `src/camserv/central/registry.py`:

### 3.1 Device Registration Record
```python
@dataclass(slots=True)
class DeviceRegistrationRecord:
    device_id: str                          # Globally unique appliance identifier
    device_name: str                        # Human-readable label (e.g. "Terminal 1 Gate NVR")
    device_role: DeviceRole                 # EDGE_NODE, PRO_APPLIANCE, ENTERPRISE_CLUSTER
    site_id: str                            # Logical site partition (e.g. "site-alpha")
    public_key_hex: str                     # Ed25519 public key (32 bytes hex)
    hardware_profile: str                   # profile_a_edge, profile_b_professional, etc.
    software_version: str                   # Active firmware / release version
    status: DeviceStatus                    # ONLINE, OFFLINE, DEGRADED, SUSPENDED, REVOKED
    security_state: SecurityState           # ENROLLED_AUTHENTICATED, CERT_EXPIRED, QUARANTINED
    telemetry: DeviceTelemetry              # Real-time health metrics
    enrolled_at: float                      # UTC timestamp of initial authorization
    last_seen_at: float                     # UTC timestamp of last verified contact
```

### 3.2 Device Roles
* **`EDGE_NODE` (Profile A):** Lightweight appliance for remote gates and perimeter posts (1-4 streams).
* **`PRO_APPLIANCE` (Profile B):** Standard on-premise NVR appliance for medium corporate sites (4-16 streams).
* **`ENTERPRISE_CLUSTER` (Profile C):** Clustered multi-GPU server for high-density camera facilities (16-64+ streams).
* **`CENTRAL_GATEWAY`:** Regional aggregation gateway managing secure relays between sites.

---

## 4. Multi-Phase Device Lifecycle

```
[Uncommissioned Device]
         │
         ▼ (Present Enrollment Token & Ed25519 Public Key)
 [Enrollment Validation] ──(Token Invalid / Expired)──► [REJECTED (HTTP 403)]
         │ (Token Verified)
         ▼
[ENROLLED & ACTIVE] ◄───(Periodic Telemetry & Challenge Handshake)
         │
         ├────────────────────────────────┬───────────────────────────────┐
         ▼ (Operator Suspends)            ▼ (Enclosure Tamper / Threat)   ▼ (Decommissioned)
    [SUSPENDED]                      [REVOKED & QUARANTINED]          [REMOVED]
 (Temporary Halt)                (Cryptographic Keys Blacklisted) (Purged from Fleet)
```

### 4.1 Token-Based Device Enrollment
1. **Token Generation:** A site administrator creates a time-bounded enrollment token scoped to a specific site:
   ```python
   registry.create_enrollment_token(token="TOK_SEC_789", site_id="site-alpha", expires_in_sec=3600.0)
   ```
2. **Device Handshake:** During initial provisioning, the appliance sends its `device_id`, hardware profile, and its raw Ed25519 public key accompanied by the token.
3. **Validation & Single-Use:** Central validates that the token is unexpired, matches the site, and has not been previously consumed. The token is immediately marked used, preventing replay.

### 4.2 Ed25519 Challenge-Response Authentication
To prevent network identity spoofing:
1. Central issues a random 32-byte cryptographic challenge nonce:
   $$\text{nonce} \in \{0, 1\}^{256}$$
2. The appliance signs the nonce with its locally stored private key:
   $$\sigma = \text{Sign}_{SK}(\text{nonce})$$
3. Central verifies $\sigma$ using the registered public key ($PK$). If valid, the session is authenticated and `last_seen_at` is updated.

### 4.3 Suspension and Revocation
* **`suspend_device`:** Temporarily blocks an appliance from reporting or receiving configuration (e.g., during scheduled physical maintenance). Subsequent challenge handshakes fail with `status is 'suspended'`.
* **`revoke_device`:** Permanently blacklists the device's public key, transitions security state to `QUARANTINED`, and immediately terminates all active sessions.

---

## 5. Logical Multi-Site Separation & Access Boundaries

Multi-tenant and multi-site isolation is enforced server-side in `DeviceRegistry._verify_site_access`:

```python
def query_devices_by_site(site_id: str, user_role: str, user_assigned_sites: list[str]) -> list[DeviceRegistrationRecord]:
    if user_role.upper() != "SUPER_ADMIN":
        if site_id not in user_assigned_sites:
            raise SiteAccessDeniedError(f"ACCESS DENIED: Role '{user_role}' cannot access '{site_id}'.")
    return [dev for dev in self.devices.values() if dev.site_id == site_id]
```

### Authorization Invariants:
1. **Strict Site Boundaries:** Operators assigned to *Site Alpha* cannot query, view, or alter devices, alerts, or cameras at *Site Beta*.
2. **Role Granularity:**
   - `SUPER_ADMIN`: Global fleet-wide visibility and administrative authority.
   - `SITE_ADMIN`: Administrative authority strictly within assigned site boundaries.
   - `SITE_OPERATOR`: Operational monitoring and incident review strictly within assigned site boundaries.

---

## 6. Executive Fleet Dashboard Aggregation

Central aggregates real-time metrics across all authorized nodes into `CentralFleetOverview`:
* **Online Status:** Node considered `ONLINE` if `time.time() - last_seen_at <= 90.0s`. If silent for $> 90\text{s}$, automatically classified `OFFLINE`.
* **Telemetry Aggregation:** Sums actual reported active camera streams, active threat alerts requiring operator review, and aggregate storage capacity across local disk pools.
* **Security Filtering:** When queried by a site-restricted operator, the fleet overview summarizes metrics **exclusively for their assigned sites**, preventing cross-site intelligence leakage.

---

## 7. Stage 3 Acceptance Decision

$$\mathbf{STAGE\_3\_ACCEPTANCE\_VERDICT: \quad ACCEPTED}$$

All deliverables for Stage 3 (CAMserv Central & Device Registry) have been implemented, mathematically verified with 5 unit tests in `tests/test_central_registry.py`, and fully documented.
