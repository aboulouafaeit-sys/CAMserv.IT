# ADR-002: ONVIF Profile S/T and NVR Interoperability Framework

## Status
Accepted

## Context
Commercial security deployments interface with diverse IP camera manufacturers (Hikvision, Dahua, Axis, Hanwha, Bosch) and existing Network Video Recorders (NVRs). Connecting solely via static RTSP URLs limits dynamic camera discovery, PTZ control, multi-stream negotiation, and health telemetry.

## Decision
1. Implement an ONVIF discovery and device service module (`src/camserv/acquisition/onvif.py`) conforming to WS-Discovery and ONVIF Profile S/T standards.
2. Differentiate three operational deployment topologies:
   - **Topology A (NVR Interconnect):** CAMserv reads RTSP sub-streams from existing enterprise NVRs without taking direct ownership of camera hardware.
   - **Topology B (Co-located Edge):** CAMserv runs alongside third-party VMS/NVR on dedicated edge compute appliances.
   - **Topology C (Direct Appliance):** CAMserv operates as the primary recording and analytics appliance directly discovering and managing IP cameras.
3. Build an automated NVR compatibility testing harness to validate stream stability, codec negotiation (H.264, H.265, MJPEG), and reconnect latency.

## Consequences
- Positive: Broad compatibility with commercial enterprise cameras; robust automated stream discovery.
- Negative: Requires handling vendor-specific ONVIF quirks and XML parsing overhead.
