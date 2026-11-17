# CAMserv — Phase 26.1: Sentinel Adversarial Hardening & Heuristics Audit
## Administrator Lockout DoS Defense, Mobile IP Roaming & Memory Boundary Verification

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Phase:** 26.1 — Identity Security Verification & Adversarial Hardening  
**Target Subsystem:** `camserv.security.identity.sentinel.CAMservSentinelIdentity`  
**Evaluation Focus:** Adversarial DoS, False-Positive Session Termination & Memory Exhaustion  
**Status:** **AUDITED, REMEDIATED & QUALIFIED**  

---

## 1. Executive Summary of Sentinel Vulnerability Audit

While Phase 26 established adaptive brute-force detection and BOLA mitigation, adversarial inspection revealed two critical operational vulnerabilities:
1. **Administrator Lockout Denial-of-Service:** An unauthenticated network adversary could trivially lock out the appliance's local administrator by repeatedly sending 5 invalid password attempts for `"admin"`, disabling administrative access during a critical security incident.
2. **False-Positive Session Termination on Roaming Networks:** A rigid policy that treated every IP address change as session theft immediately disconnected legitimate mobile operators and VPN users upon roaming between cellular and WiFi.

Both vulnerabilities have been remediated, verified, and qualified in Phase 26.1.

---

## 2. Adversarial Test Results & Remediations

### 2.1 Attack Scenario A: Remote Administrator Lockout DoS
- **Adversary Vector:** Attacker sends repeated failed logins for the primary administrative user from an untrusted network IP.
- **Pre-Remediation Behavior:** The database marked `users.status = 'locked'` and set `locked_until_utc = now + 300s`. The genuine administrator was blocked from accessing the local appliance console.
- **Phase 26.1 Remediation (`admin_lockout_protection = True`):**
  - When the targeted account is an administrator (`is_administrator == True` or role is `admin`), Sentinel **refuses** to set the database account status to `locked`.
  - Instead, Sentinel applies the maximum progressive delay (`max_progressive_delay_sec = 8.0s`), requires mandatory AAL2 MFA verification, and logs `SENTINEL_ADMIN_BRUTE_FORCE_THROTTLED`.
  - The local administrator console (`127.0.0.1` and local physical terminal) remains operational and accessible.
- **Verification:** Verified in adversarial tests (`test_admin_lockout_protection_remote_dos_prevention`).

### 2.2 Attack Scenario B: False-Positive Session Drops on Legitimate IP Roaming
- **Operational Reality:** Modern surveillance operators utilize laptops, rugged tablets, and mobile clients that switch between corporate LAN, Wi-Fi 6, and 4G/5G cellular connections, causing the client IP to mutate.
- **Pre-Remediation Behavior:** Any mismatch between `session.ip_address` and `incoming_ip` immediately revoked the session, forcing operators to re-authenticate and disrupting active live video monitoring.
- **Phase 26.1 Remediation (`allow_ip_roaming` & `require_step_up_on_ip_change`):**
  - Configurable policy options added to `SentinelConfig`:
    - `allow_ip_roaming = True`: For environments with dynamic VPNs or mobile devices, IP mutation emits an informational `SENTINEL_SESSION_IP_ROAMING` audit event and smoothly updates the session's active IP without dropping video playback.
    - `require_step_up_on_ip_change = True`: Emits a step-up challenge prompt rather than hard revoking the session.
    - Default Strict Mode (`allow_ip_roaming = False`): Retained for high-security airgapped control rooms where operator workstations have fixed static IP allocations.
- **Verification:** Verified in adversarial tests (`test_sentinel_mobile_ip_roaming_policy`).

### 2.3 Attack Scenario C: Memory Exhaustion via Synthetic Username Flooding
- **Adversary Vector:** Attacker floods login endpoints with 500,000 distinct, non-existent usernames and random IPs to bloat in-memory failure tracking deques.
- **Defense Mechanism:**
  - `_prune_expired()` removes all records older than the sliding window (`window_sec = 300.0s`).
  - Strict ceiling: `max_tracked_entries = 1000`. Memory footprint is permanently bounded to $\le 10$ MiB regardless of attack volume.
- **Verification:** Verified in adversarial tests (`test_sentinel_bounded_memory_under_username_flood`).

---

## 3. Heuristic Configuration Matrix

| Sentinel Setting | Default Value | Security Impact | Recommended Deployment Tuning |
| :--- | :---: | :--- | :--- |
| `window_sec` | 300.0s (5 min) | Time window for correlating failures | Maintain 300s; increase to 600s in high-security facilities |
| `max_account_failures` | 5 | Threshold for locking standard client accounts | 5 attempts (NIST SP 800-63B compliant) |
| `max_ip_failures` | 20 | Threshold for blocking offending IP address | 20 attempts across accounts (mitigates distributed brute force) |
| `admin_lockout_protection` | **`True`** | Prevents remote DoS lockout of administrators | **Mandatory True** on standalone edge appliances |
| `allow_ip_roaming` | `False` | Determines whether IP change drops session | Set `True` if operators use roaming tablets / dynamic VPNs |
| `exempt_ips` | `{"127.0.0.1", "::1"}` | Addresses immune from network IP blocks | Local appliance loopback console always exempt |
