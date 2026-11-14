# CAMserv Observability, Metrics & Diagnostics Plan
**Document ID:** OBS-PLAN-2026-001  
**Author:** Principal SRE & Telemetry Systems Architect  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Standards:** OpenTelemetry v1.30, Prometheus Metric Exposition Format, structlog JSONL

---

## 1. Observability Architecture

In enterprise security deployments, silent degradation is intolerable. CAMserv incorporates the **Three Pillars of Observability** (Metrics, Structured Logs, and Traces):

```
+---------------------------------------------------------------------------------+
|                       CAMSERV OBSERVABILITY TELEMETRY BUS                       |
|                                                                                 |
|   +-----------------------+  +-----------------------+  +--------------------+  |
|   | 1. Prometheus Metrics |  | 2. Structured Logs   |  | 3. OTel Tracing    |  |
|   | Endpoint: /metrics    |  | structlog JSONL       |  | W3C TraceContext   |  |
|   | - Ingest FPS          |  | - Contextual Key/Vals |  | - Ingest to Infer  |  |
|   | - Inference Latency   |  | - SHA-256 Hash Chain  |  | - Infer to Storage |  |
|   | - Drop-Oldest Sat     |  | - Masked PII / IPs    |  | - Span Latency     |  |
|   +-----------+-----------+  +-----------+-----------+  +---------+----------+  |
|               |                          |                        |             |
+---------------+--------------------------+------------------------+-------------+
                |                          |                        |
                v                          v                        v
        Prometheus / Grafana      Local Audit Vault         Jaeger / Grafana Tempo
```

---

## 2. Core Prometheus Metrics Specification

| Metric Identifier | Type | Labels | Description |
|---|---|---|---|
| `camserv_camera_ingest_fps` | Gauge | `camera_id`, `codec` | Actual frame capture rate per camera stream. |
| `camserv_inference_latency_seconds` | Histogram | `model`, `device`, `tier` | Neural inference latency distribution ($640 \times 640$ tensor). |
| `camserv_tracking_objects_active` | Gauge | `camera_id`, `class` | Count of active tracked objects currently tracked in scene. |
| `camserv_queue_saturation_ratio` | Gauge | `queue_name`, `policy` | Bounded ring queue fullness percentage ($[0.0, 1.0]$). |
| `camserv_frames_dropped_total` | Counter | `camera_id`, `reason` | Total frames dropped by backpressure `DROP_OLDEST` policy. |
| `camserv_threat_score_value` | Gauge | `camera_id`, `event_id` | Real-time threat score calculation ($[0, 100]$). |
| `camserv_vault_bytes_written_total` | Counter | `tier`, `encryption` | Cumulative encrypted bytes committed to forensic vault. |
| `camserv_hardware_vram_used_bytes` | Gauge | `gpu_index` | Dedicated GPU VRAM consumption in bytes. |

---

## 3. Structured Logging & Distributed Tracing

* **Contextual JSONL Logs:** Every log line emitted by `structlog` includes ISO-8601 monotonic timestamps, process PID, thread ID, camera UUID, and correlation trace ID:
  ```json
  {
    "timestamp": "2026-11-14T10:45:00.124Z",
    "level": "info",
    "logger": "camserv.inference.detector",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "camera_id": "cam-gate-north",
    "detections_count": 3,
    "inference_ms": 4.12,
    "device": "cuda:0"
  }
  ```
* **W3C Distributed Trace Context:** Spans trace individual video frames from camera socket ingestion, through software ISP, shared memory ring buffer, ONNX inference, and disk sealing.
