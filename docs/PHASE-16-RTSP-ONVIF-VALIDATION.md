# Phase 16: RTSP Stream & ONVIF Protocol Validation on Windows

**Target Release:** 0.10.0-alpha2  
**Host Environment:** Windows 11 Pro 64-bit  
**Evaluated Modules:** `src/camserv/streaming/`, `src/camserv/onvif/`  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Scope & Objective

Verify that CAMserv's IP camera streaming and ONVIF discovery protocols operate reliably on Windows 11 under native Windows networking, socket architectures, and Windows Defender Firewall constraints.

---

## 2. Ingestion Protocols on Windows

### 2.1 RTSP Protocol Handling (RFC 2326)
- **Transport Mechanisms:** RTSP interleaved TCP (transport profile `RTP/AVP/TCP`) and UDP (`RTP/AVP/UDP`).
- **Windows Socket Optimization:**
  - Standard non-blocking sockets with `SO_REUSEADDR`.
  - Buffer sizing adjusted for High-Definition stream ingestion (2MB socket receive buffer).
  - Handles jitter and network drops via reconnect loop with exponential backoff.

### 2.2 ONVIF Device Discovery & Profile S/T Integration
- **WS-Discovery Probes:** Multicast probe packets transmitted to `239.255.255.250:3702` via UDP.
- **Firewall Integration:** `WindowsFirewallManager` provisions rule `CAMserv ONVIF Discovery` on port 3702 UDP to prevent Windows Defender Firewall from discarding inbound probe responses from cameras.
- **PTZ Controls:** Continuous and absolute PTZ commands transmitted over SOAP/HTTP.

---

## 3. Windows Compatibility Testing

| Feature | Windows Behavior | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **RTSP TCP Ingestion** | Interleaved packets decoded via FFmpeg/PyAV pipeline. | Unit test stream parser | **PASS** |
| **RTSP UDP Ingestion** | Unicast UDP packet reception on ephemeral ports. | Socket listener fixture | **PASS** |
| **ONVIF WS-Discovery** | Multicast probe broadcast and XML response parsing. | XML parser & WS-Discovery tests | **PASS** |
| **Digest Authentication** | HTTP Digest auth computed for ONVIF requests. | Auth test vectors | **PASS** |
| **Firewall Ingress** | Ports 8554 TCP and 3702 UDP authorized via netsh. | Firewall synthesis test | **PASS** |

---

## 4. Verification Evidence

- Integrated with existing streaming test suites: all streaming tests passed without Windows socket errors.
- Firewall rule synthesis verified in `test_windows_firewall_rule_synthesis`.
