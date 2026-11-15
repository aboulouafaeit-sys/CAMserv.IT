# CAMserv Live Streaming Gateway Architecture

**Document ID:** ARCH-STREAM-2026-001  
**Classification:** Technical Architecture Specification  
**Version:** 1.0.0  
**Date:** November 15, 2026  

---

## 1. Overview and Design Objectives

The **CAMserv Streaming Gateway** provides a multi-protocol, low-latency live video distribution subsystem capable of streaming camera feeds to web browsers, mobile applications, and enterprise monitoring stations without proprietary browser plugins.

### Primary Objectives:
1. **Low Latency:** Sub-second glass-to-glass latency via WebRTC for real-time monitoring and PTZ control.
2. **Universal Compatibility:** Fallback to Low-Latency HLS (LL-HLS) and Media Source Extensions (MSE) for multi-browser support, with MJPEG as a zero-dependency diagnostic fallback.
3. **Mandatory Privacy Enforcement:** All outgoing streams pass through the `FailClosedPrivacyPipeline`. Unmasked frames can never reach live viewers.
4. **Adaptive Quality:** Dynamic resolution and bitrate adaptation based on client connection quality and network backpressure.

---

## 2. Multi-Protocol Streaming Hierarchy

```
                            ┌──────────────────────────────────┐
                            │    Camera Ingestion Pipeline     │
                            └────────────────┬─────────────────┘
                                             │
                                             ▼
                            ┌──────────────────────────────────┐
                            │    Fail-Closed Privacy Filter    │
                            │    (Faces/Plates/Zones Masked)   │
                            └────────────────┬─────────────────┘
                                             │
                                             ▼
                            ┌──────────────────────────────────┐
                            │     Streaming Multiplexer        │
                            └────────────────┬─────────────────┘
                                             │
         ┌───────────────────────────────────┼───────────────────────────────────┐
         ▼                                   ▼                                   ▼
┌─────────────────┐                 ┌─────────────────┐                 ┌─────────────────┐
│     WebRTC      │                 │  Low-Latency    │                 │      MJPEG      │
│  (Ultra-Low     │                 │   HLS / MSE     │                 │ (Compatibility  │
│  < 500ms RT)    │                 │  (1.5s - 3s)    │                 │    Fallback)    │
└────────┬────────┘                 └────────┬────────┘                 └────────┬────────┘
         │                                   │                                   │
         ▼                                   ▼                                   ▼
  Desktop / PTZ Ops                 Multi-View Grids                     Diagnostics
```

### 2.1 WebRTC Protocol Engine
- **Target Latency:** $150\text{ ms} - 500\text{ ms}$.
- **Transport:** UDP with ICE/STUN candidates, DTLS-SRTP encryption.
- **Use Cases:** Active camera inspection, manual PTZ tracking, interactive monitoring.
- **Signaling:** Handled via FastAPI WebSocket endpoint `/api/v1/stream/{camera_id}/webrtc/signal` exchanging SDP offers, answers, and ICE candidates.

### 2.2 Low-Latency HLS (LL-HLS) & MSE Engine
- **Target Latency:** $1.5\text{ s} - 3.0\text{ s}$.
- **Transport:** HTTP/2 or HTTP/1.1 chunked transfer over standard TLS.
- **Packaging:** Fragmented MP4 (fMP4) with short segment durations (1.0s to 2.0s) and partial segments (333ms).
- **Use Cases:** Large multi-camera grid views (e.g., $4\times 4$ or $8\times 8$ layouts), mobile clients, cellular networks.
- **Endpoint:** `/api/v1/stream/{camera_id}/hls/live.m3u8`.

### 2.3 Motion JPEG (MJPEG) Compatibility Fallback
- **Target Latency:** $500\text{ ms} - 1.0\text{ s}$.
- **Transport:** HTTP multipart/x-mixed-replace stream.
- **Use Cases:** Low-resource IoT displays, debugging tools, environments where H.264 decoding is unsupported.
- **Endpoint:** `/api/v1/stream/{camera_id}/mjpeg`.

---

## 3. Stream Health & Telemetry Metrics

The gateway measures operational streaming health continuously:
- **Bitrate:** Bits per second delivered per client stream.
- **Frames Delivered:** Ingested vs. rendered frames count.
- **Latency:** Measured end-to-end processing and network transmission time.
- **Dropped Frames:** Backpressure counter tracking dropped frames due to slow client connections.
- **Connection Health:** Monitored via WebSocket keepalive heartbeats (`ping`/`pong`).
