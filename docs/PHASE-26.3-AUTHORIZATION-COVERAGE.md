# CAMserv — Phase 26.3: Authorization Coverage Across Backend Entry Points

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Subsystem:** Zero-Trust Object-Level Authorization (`src/camserv/security/identity/authorization.py`, `src/camserv/api/routes.py`)  
**Document:** `docs/PHASE-26.3-AUTHORIZATION-COVERAGE.md`  
**Classification:** Complete Backend Authorization Audit & BOLA/IDOR Defense Map  

---

## 1. Executive Summary & Zero-Trust Deny-by-Default Architecture

CAMserv enforces a strict **Deny-by-Default** authorization model across all REST endpoints and WebSocket event streams. Access evaluation follows a 6-tier deterministic pipeline:
1. **Tier 0 (Emergency Lockdown Check):** Non-whitelisted operations are immediately rejected during active lockdown.
2. **Tier 1 (Account Status):** Account must be `ACTIVE` (not suspended, pending, or locked).
3. **Tier 2 (Session Validity):** Session must be active, unrevoked, and within idle/absolute timeouts.
4. **Tier 3 (Authentication Assurance Level):** High-impact actions (`evidence:export`, `system:config`, etc.) mandate MFA (`AAL2`).
5. **Tier 4 (Object-Level Resource Scopes):** Explicit user scopes take precedence over broad roles.
6. **Tier 5 (Role-Level Grants & IDOR/BOLA Camera Isolation):** User's assigned role must permit the action, and target camera resources must match assigned scopes.

---

## 2. Exhaustive API Route Authorization Inventory

Every API route defined in `src/camserv/api/routes.py` and `app.py` has been systematically audited:

| # | Endpoint & Method | Handler | Action Name | Required AAL | Minimum Role | Lockdown Status | BOLA / IDOR Scope Check |
| :-: | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **1** | `GET /health` | `root_health` | `system:status` | AAL1 | Anonymous | **ALLOWED** | Global unauthenticated status |
| **2** | `POST /api/v1/auth/token` | `login` | `account:login` | AAL1 | Anonymous | **BLOCKED (Client)** | Direct login endpoint; Sentinel enforced |
| **3** | `POST /api/v1/auth/refresh` | `refresh_token` | `account:refresh` | AAL1 | Authenticated | **BLOCKED (Client)** | Session token rotation |
| **4** | `GET /api/v1/cameras` | `list_cameras` | `camera:view` | AAL1 | Viewer | **BLOCKED** | Filtered by user camera scopes |
| **5** | `GET /api/v1/cameras/{id}` | `get_camera` | `camera:view` | AAL1 | Viewer | **BLOCKED** | BOLA checked: target camera in assigned scopes |
| **6** | `POST /api/v1/cameras` | `add_camera` | `camera:create` | AAL2 | Admin | **BLOCKED** | System-wide administrative action |
| **7** | `PUT /api/v1/cameras/{id}` | `update_camera` | `camera:configure` | AAL2 | Admin | **BLOCKED** | Camera configuration isolation |
| **8** | `DELETE /api/v1/cameras/{id}`| `delete_camera` | `camera:delete` | AAL2 | Admin | **BLOCKED** | Permanent camera asset removal |
| **9** | `GET /api/v1/events` | `query_events` | `event:view` | AAL1 | Viewer | **BLOCKED** | Filtered by camera assignment |
| **10**| `GET /api/v1/events/{id}` | `get_event` | `event:view` | AAL1 | Viewer | **BLOCKED** | BOLA checked: parent camera in user scope |
| **11**| `POST /api/v1/events/{id}/verify`| `verify_event`| `event:verify` | AAL1 | Auditor | **BLOCKED** | Forensic cryptographic verification |
| **12**| `GET /api/v1/detections/recent`| `get_recent_detections`| `analytics:view` | AAL1 | Viewer | **BLOCKED** | Real-time inference feed |
| **13**| `GET /api/v1/tracking/active`| `get_active_tracks` | `analytics:view` | AAL1 | Viewer | **BLOCKED** | Object tracking state |
| **14**| `GET /api/v1/system/health` | `health_check` | `system:status` | AAL1 | Authenticated | **ALLOWED** | Subsystem telemetry & diagnostic |
| **15**| `GET /api/v1/system/metrics`| `system_metrics` | `system:status` | AAL1 | Auditor | **ALLOWED** | Resource consumption metrics |
| **16**| `GET /api/v1/config` | `get_config` | `system:config` | AAL2 | Admin | **BLOCKED** | Platform configuration |
| **17**| `PUT /api/v1/config` | `update_config` | `system:config` | AAL2 | Admin | **BLOCKED** | Appliance setting modification |
| **18**| `GET /api/v1/audit` | `query_audit` | `audit:view` | AAL1 | Auditor | **BLOCKED** | Read tamper-evident security ledger |
| **19**| `GET /api/v1/groups` | `list_groups` | `camera:view` | AAL1 | Viewer | **BLOCKED** | Logical camera groupings |
| **20**| `POST /api/v1/groups` | `create_group` | `camera:configure` | AAL2 | Admin | **BLOCKED** | Group creation |
| **21**| `DELETE /api/v1/groups/{id}` | `delete_group` | `camera:configure` | AAL2 | Admin | **BLOCKED** | Group deletion |
| **22**| `GET /api/v1/recordings` | `list_recordings` | `recording:view` | AAL1 | Viewer | **BLOCKED** | Filtered by camera permissions |
| **23**| `GET /api/v1/recordings/timeline`| `get_recording_timeline`| `recording:view`| AAL1 | Viewer | **BLOCKED** | Visual timeline scrub metadata |
| **24**| `POST /api/v1/recordings/export`| `export_recording_clip`| `evidence:export` | AAL2 | Operator | **BLOCKED** | Clipped video export |
| **25**| `POST /api/v1/recordings/export-forensic`| `export_forensic_evidence`| `evidence:export` | AAL2 | Auditor | **BLOCKED** | Signed judicial export package |
| **26**| `GET /api/v1/recordings/{id}`| `get_recording` | `recording:view` | AAL1 | Viewer | **BLOCKED** | BOLA checked: recording camera scope |
| **27**| `POST /api/v1/recordings/{id}/judicial-hold`| `set_recording_judicial_hold`| `evidence:hold`| AAL2 | Auditor | **BLOCKED** | Quorum-gated preservation lock |
| **28**| `GET /api/v1/recordings/{id}/segments`| `list_recording_segments`| `recording:view`| AAL1 | Viewer | **BLOCKED** | Granular segment enumeration |
| **29**| `DELETE /api/v1/recordings/{id}`| `delete_recording`| `recording:delete` | AAL2 | Admin | **BLOCKED** | Quorum-gated forensic purge |
| **30**| `GET /api/v1/stream/{id}/mjpeg`| `stream_mjpeg` | `stream:view` | AAL1 | Viewer | **BLOCKED** | Live video stream; camera checked |
| **31**| `GET /api/v1/stream/{id}/hls/live.m3u8`| `stream_hls_playlist`| `stream:view`| AAL1 | Viewer | **BLOCKED** | HLS live streaming |
| **32**| `POST /api/v1/stream/{id}/webrtc/offer`| `stream_webrtc_offer`| `stream:view`| AAL1 | Viewer | **BLOCKED** | WebRTC ultra-low-latency feed |
| **33**| `GET /api/v1/cameras/{id}/ptz/capabilities`| `get_ptz_capabilities`| `camera:view`| AAL1 | Viewer | **BLOCKED** | PTZ metadata query |
| **34**| `POST /api/v1/cameras/{id}/ptz/move`| `ptz_move` | `camera:ptz` | AAL1 | Operator | **BLOCKED** | PTZ motor control command |
| **35**| `POST /api/v1/cameras/{id}/ptz/stop`| `ptz_stop` | `camera:ptz` | AAL1 | Operator | **BLOCKED** | PTZ motor stop command |
| **36**| `GET /api/v1/cameras/{id}/ptz/presets`| `list_ptz_presets`| `camera:view` | AAL1 | Viewer | **BLOCKED** | Preset position query |
| **37**| `POST /api/v1/cameras/{id}/ptz/presets`| `create_ptz_preset`| `camera:ptz` | AAL1 | Operator | **BLOCKED** | Preset position recording |
| **38**| `POST /api/v1/cameras/{id}/ptz/presets/{p}/goto`| `goto_ptz_preset`| `camera:ptz`| AAL1 | Operator | **BLOCKED** | Move to preset coordinate |
| **39**| `POST /api/v1/analytics/{id}/tripwires`| `add_tripwire` | `analytics:configure`| AAL2 | Operator | **BLOCKED** | Virtual line tripwire |
| **40**| `POST /api/v1/analytics/{id}/zones`| `add_polygon_zone`| `analytics:configure`| AAL2 | Operator | **BLOCKED** | Polygon intrusion zone |
| **41**| `WS /api/v1/ws/events` | `websocket_events` | `event:view` | AAL1 | Viewer | **BLOCKED** | WebSocket real-time event pump |

---

## 3. Adversarial Authorization Attack Vectors & Verification

### 1. BOLA / IDOR Horizontal Camera Isolation
- **Attack:** User `operator_east` with scope limited to `camera_east` submits requests targeting `camera_west` (`GET /api/v1/stream/camera_west/mjpeg` or `POST /api/v1/cameras/camera_west/ptz/move`).
- **Defense Result:** `ZeroTrustPolicyEngine.authorize()` inspects explicit resource scopes. Since `camera_west` is not in `user.scopes`, access is denied: `Role 'operator' does not permit action 'stream:view' on camera 'camera_west'`.

### 2. Privilege Vertical Escalation
- **Attack:** User with `VIEWER` role submits `POST /api/v1/recordings/export` or `POST /api/v1/cameras/cam1/ptz/move`.
- **Defense Result:** `ROLE_BASE_PERMISSIONS` strictly rejects the request: `Role 'viewer' does not permit action 'camera:ptz'`.

### 3. Step-Up Authentication Enforcement (AAL2)
- **Attack:** User with `OPERATOR` role attempts to invoke `POST /api/v1/recordings/export-forensic` with a basic single-factor session (`AAL1`).
- **Defense Result:** Policy engine halts execution with `StepUpRequiredError: Action 'evidence:export' requires multi-factor authentication (AAL2)`.

---

## 4. Adversarial Verification Test Suite

Tested in `tests/test_phase26_3_adversarial.py`:
1. `test_authorization_bola_idor_cross_camera_denied`: PASS
2. `test_authorization_vertical_escalation_denied`: PASS
3. `test_authorization_step_up_mandatory_for_evidence_export`: PASS
4. `test_authorization_lockdown_blocks_all_client_actions`: PASS
5. `test_authorization_lockdown_permits_video_ingestion`: PASS
