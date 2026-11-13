# CAMserv Operator & System Administrator User Guide

**Enterprise Security Intelligence Platform**  
**Version:** 1.0 (Production Release)

---

## 1. Getting Started & User Interface

CAMserv features a responsive, single-page command console designed for 24/7 security operations centers (SOC) and mobile dispatch stations.

### 1.1 Command Navigation Rail
The left sidebar provides instant access to the 13 operational modules, grouped logically:
- **Operations:** Executive Overview, Live Monitoring, Camera Management, Intelligent Event Center.
- **Forensics & Analytics:** Anonymous Tracking, Incident Investigation, Evidence Vault, Analytics & Reports.
- **Platform Infrastructure:** Device & NVR Integration, Privacy Management, Security & Access Control, System Health, Deployment & Config.

### 1.2 Global Controls & Shortcuts
- **Theme Switcher:** Click the `☀️ Light` / `🌙 Dark` button in the top navigation bar to toggle between Tactical Dark Mode and High-Contrast Daytime Light Mode.
- **Keyboard Shortcuts:**
  - `Ctrl + 1`: Executive Overview
  - `Ctrl + 2`: Live Monitoring Multi-View
  - `Ctrl + 3`: Camera Management
  - `Ctrl + 4`: Intelligent Event Center
  - `Ctrl + 5`: Anonymous Kinematic Tracking
  - `Ctrl + 6`: Incident Investigation Timeline
  - `Ctrl + 7`: Evidence Vault
  - `Ctrl + 8`: Visual Intelligence & Analytics
  - `Ctrl + 9`: Device & NVR Integration
  - `Ctrl + 0`: Security & RBAC Audit

---

## 2. Managing Cameras & Video Sources

### 2.1 Adding a Video Stream
1. Open **Camera Management** (`Ctrl + 3`).
2. Click **Add Camera Source**.
3. Enter:
   - **Camera Name:** Descriptive identifier (e.g., `North Gate Perimeter`).
   - **RTSP Stream URL:** `rtsp://user:pass@192.168.1.120:554/stream1`.
   - **Location Tag:** Physical zone or checkpoint.
   - **FPS Limit:** Target ingestion frame rate (default: 25 FPS).
4. Click **Connect & Calibrate**.

### 2.2 Configuring Privacy Exclusion Zones
CAMserv enforces edge-level visual privacy:
1. Select any camera in **Camera Management**.
2. Click **Configure Privacy Masks**.
3. Use your cursor to draw a polygon over sensitive non-surveillance zones (e.g., public sidewalks, neighboring residential windows).
4. Pixels within the polygon are permanently zeroed out or masked with Gaussian mosaic blur prior to AI inference and recording.

---

## 3. Intelligent Event Center & Human-in-the-Loop (HITL)

### 3.1 Epistemic Transparency Principle
CAMserv strictly follows the epistemic transparency mandate:
- **Every event carries an `is_prediction: true` flag.**
- Algorithmic inferences are **never** reported as established facts.
- Bounded probabilities $p \in [0.0, 1.0]$ reflect neural model confidence combined with multi-frame kinematic evidence.

### 3.2 Human Review Workflow
For high and critical alarms (e.g., Restricted Zone Penetration, Rapid Fall Detection, Camera Tampering):
1. Navigate to **Intelligent Event Center** (`Ctrl + 4`).
2. Pending items appear in the **Review Queue** with an amber or crimson indicator.
3. Click an incident to inspect:
   - Multi-frame observation graph (bounding box trajectories, aspect-ratio change curves).
   - High-confidence snapshot crop.
   - Kinematic velocity metrics.
4. Action Choices:
   - **Acknowledge & Dispatch:** Dispatches physical response team and seals evidence bundle.
   - **Dismiss (False Positive):** Flags the observation for model calibration feedback.

---

## 4. Anonymous Kinematic Tracking

CAMserv uses ByteTrack and BoT-SORT algorithms that operate **strictly without facial recognition or biometric signatures**:
- **Transient IDs:** Moving subjects are assigned transient integer tracking identifiers (e.g., `Track #1042`).
- **Kinematic Analysis:** Velocity vectors, dwell durations, and trajectory heading angles are calculated using Kalman filters.
- **Privacy Guarantee:** When a subject departs the surveillance frame and does not return within the association timeout (60 seconds), the tracking state is purged. No identity re-association is attempted across days or distinct facilities.

---

## 5. Evidence Vault & Forensic Cryptography

The **Evidence Vault** (`Ctrl + 7`) provides immutable, court-admissible audit packages:
1. **AES-256-GCM Encryption:** All stored video clips, metadata, and tracking logs are encrypted at rest with rotating encryption keys.
2. **Cryptographic Hash Chain:** Every recorded frame and event record is linked via continuous SHA-256 hashing. Modifying a single bit breaks the hash chain.
3. **One-Click Integrity Audit:** Click **Verify Integrity Chain** to recalculate SHA-256 hashes across all historical vault entries. The platform confirms non-tampered chain validity in real time.

---

## 6. CLI Administration

Administrators can perform core maintenance from the command line:

```bash
# Probe hardware accelerators and assigned tier
python -m camserv.main detect-hw

# Scan subnet for ONVIF cameras
python -m camserv.main nvr-scan --network 192.168.1.0/24

# Verify cryptographic evidence vault integrity
python -m camserv.main verify-evidence --vault-dir ./evidence

# Verify audit trail hash chain
python -m camserv.main audit-verify
```
