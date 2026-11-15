# CAMserv — Phase 3 Distributed Security & Communication Architecture

**Document ID:** ARCH-DIST-SEC-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Phase:** Phase 3 Stage 4 Deliverable  
**Date:** November 15, 2026  
**Status:** PRODUCTION DISTRIBUTED COMMUNICATION BLUEPRINT  
**Author / Authority:** Network Security Engineer, Distributed Systems Engineer & Cybersecurity Architect  

---

## 1. Executive Summary & Security Objectives

In enterprise distributed surveillance environments, communication channels between **CAMserv Central** and remote **AI Appliances / Edge Nodes** traverse public wide-area networks (WAN), commercial cellular uplinks (4G/5G), and untrusted corporate intranets.

**Stage 4** establishes an end-to-end zero-trust communication architecture that protects control-plane integrity, prevents packet injection or eavesdropping, ensures operational survival during extended network outages, and strictly enforces **GDPR-compliant WAN data minimization**.

### Core Distributed Security Invariants:
1. **Mutual Cryptographic Authentication:** All communication requires Mutual TLS 1.3 (mTLS) supplemented by application-layer **Ed25519 digital signatures** on every transmitted envelope. An unauthenticated packet is discarded at the wire level.
2. **Replay & Timing Attack Immunity:** Envelopes contain unique cryptographic nonces ($\text{UUIDv4}$) and strict timestamp bounds ($\Delta t \le 60\text{s}$). Reused nonces or stale timestamps trigger an immediate `ReplayAttackError`.
3. **Decoupled Local Survival:** **A network disconnection or Central outage MUST NEVER halt local camera ingestion, live privacy masking, or local encrypted vault storage.** Local edge nodes continue independent security operations indefinitely while disconnected.
4. **Strict WAN Data Minimization (GDPR Art. 5.1.c):** Continuous raw unmasked video is **mathematically barred** from wide-area transmission. Appliances transmit only health telemetry, low-bandwidth threat alerts, and SHA-256 cryptographic manifest digests.

---

## 2. Distributed Communication Protocol Architecture

```
+──────────────────────────+                             +──────────────────────────+
|  CAMserv Edge Appliance  |                             |     CAMserv Central      |
+──────────────────────────+                             +──────────────────────────+
             │                                                         │
             │ 1. Initiate mTLS 1.3 Handshake (X.509 Client Cert)      │
             ├────────────────────────────────────────────────────────►│
             │                                                         │
             │ 2. Issue Challenge Nonce                                │
             │◄────────────────────────────────────────────────────────┤
             │                                                         │
             │ 3. Send Signed Envelope (Ed25519 Signature)             │
             ├────────────────────────────────────────────────────────►│
             │    [Validate Nonce + Timestamp + Signature + Limits]    │
             │                                                         │
             │ 4. Acknowledge Batch (ACK)                              │
             │◄────────────────────────────────────────────────────────┤
```

---

## 3. Cryptographically Bound Envelope Specification

Implemented in `src/camserv/central/comm.py`:

```python
@dataclass(slots=True)
class SecureMessageEnvelope:
    message_id: str                          # Globally unique message identifier
    sender_id: str                           # Origin appliance ID
    recipient_id: str                        # Target gateway ID
    payload_type: str                        # TELEMETRY, EVENT_ALERT, MANIFEST_DIGEST, COMMAND
    payload_data: dict[str, Any]             # Structured payload dictionary
    timestamp: float                         # UTC seconds
    nonce: str                               # Unique cryptographic nonce
    signature_hex: str                       # 64-byte Ed25519 digital signature
```

### Canonical Signing Construction:
To prevent JSON serialization variations (whitespace, field order) from breaking signature validation, the envelope generates a deterministic canonical byte stream:
$$\text{payload\_hash} = \text{SHA256}(\text{json.dumps}(payload, \text{sort\_keys}=\text{True}))$$
$$\text{canonical\_bytes} = \text{MSG\_V1} \parallel \text{id} \parallel \text{sender} \parallel \text{recipient} \parallel \text{type} \parallel \text{ts} \parallel \text{nonce} \parallel \text{payload\_hash}$$
$$\sigma = \text{Sign}_{SK}(\text{canonical\_bytes})$$

---

## 4. Replay Protection, Rate Limiting & Denial-of-Service Defense

### 4.1 Sliding-Window Nonce Cache
The receiver maintains an in-memory cache of active nonces. If an incoming message presents a nonce that has already been recorded within the expiration window ($2 \times \text{max\_clock\_skew}$), the message is rejected with `ReplayAttackError`.

### 4.2 Clock Skew Rejection
Messages whose UTC timestamp differs from the receiver's wall-clock time by more than $60\text{s}$ are immediately dropped, preventing delayed replay of captured historical packets.

### 4.3 Node Rate Limiting
A token bucket algorithm limits each connected appliance to a maximum message rate (default: 120 messages/minute). Bursts exceeding the quota raise `RateLimitExceededError`, preventing compromised or misconfigured edge nodes from overwhelming the central management bus.

---

## 5. WAN Data Minimization Enforcement

In strict compliance with European Data Protection Board (EDPB) surveillance guidelines, CAMserv Central prohibits transmitting high-bandwidth raw visual data over public channels.

### Prohibited Fields:
Attempting to include any of the following keys in `payload_data`:
* `raw_video`
* `raw_frame`
* `unmasked_stream`
* `raw_image`

instantly triggers `DataMinimizationViolationError`. The appliance must send only derivative bounding boxes, posture classifications, event severity scores, and cryptographic SHA-256 manifests. Pristine evidence can only be inspected locally on the appliance or exported via on-premise dual-quorum authorization.

---

## 6. Store-and-Forward Offline Resilience

Managed by `OfflineMessageBuffer` in `src/camserv/central/comm.py`:
* **Network Interruption Behavior:** When an appliance loses WAN connectivity to Central, generated event alerts and manifest digests are enqueued in the local buffer queue (capacity: 10,000 items).
* **Prioritized Buffer Eviction:** If the buffer fills under extended disconnection, old non-critical telemetry frames are dropped while high-severity threat alerts are strictly retained.
* **Flushing upon Reconnection:** Upon network restoration, messages are dispatched in sequential batches (50 items/batch). Once Central responds with an explicit cryptographic ACK, the batch is acknowledged and removed from disk.
* **Local Operational Non-Interference:** Buffer operations are completely decoupled from camera decoding and vault recording. Local video storage continues at full FPS regardless of network state.

---

## 7. Stage 4 Acceptance Decision

$$\mathbf{STAGE\_4\_ACCEPTANCE\_VERDICT: \quad ACCEPTED}$$

All deliverables for Stage 4 (Secure Distributed Communication) are implemented, verified by 5 unit tests in `tests/test_distributed_comm.py`, and documented.
