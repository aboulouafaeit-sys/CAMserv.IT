# Phase 1B Video Ingestion Re-Architecture Report
**Document ID:** P1B-INGEST-2026-001  
**Author:** Senior Video Streaming Specialist & Multiprocessing Systems Engineer  
**Date:** November 14, 2026  
**Status:** **PHASE 1B ACCEPTED**  
**Target:** Video ingestion re-architecture, eliminating in-process C-library video decoding risks and providing robust camera supervision abstractions.

---

## 1. Architectural Motivation & Problem Definition

### 1.1 Legacy Vulnerability (In-Process Capture)
In the baseline CAMserv architecture (`b65fda4`), video frame acquisition was handled via `cv2.VideoCapture` executed inside an `asyncio.to_thread` pool within the main server process.
* **Failure Blast Radius:** Any native segfault, buffer overrun, corrupted H.264/H.265 NAL unit, or RTSP protocol panic inside libavformat/OpenCV brought down the entire CAMserv daemon, terminating all other camera feeds, active inference models, and the web API.
* **GIL & Thread Contention:** Native thread pooling inside Python's primary process introduced lock contention during heavy decode operations across multiple high-resolution streams.

### 1.2 Remediated Architecture
Under Phase 1B:
1. Video ingestion is decoupled from the main process into dedicated, isolated child operating system worker processes (`camserv-worker-<camera_id>`).
2. The core platform accesses camera streams via high-level abstractions:
   * `CameraWorkerSupervisor`: Manages worker process lifecycles, health checks, heartbeats, and zero-downtime respawns.
   * `IngestionManager`: Coordinates multi-camera ingestion across appliance streams.
   * `CameraStream`: Transparently bridges isolated workers with the standard `FrameSource` async iterator protocol.

---

## 2. Component Design & Implementation

### 2.1 Multi-Camera Ingestion Manager (`src/camserv/acquisition/ingestion_manager.py`)
```
                                +---------------------------+
                                |     IngestionManager      |
                                +-------------+-------------+
                                              |
                     +------------------------+------------------------+
                     |                                                 |
         +-----------v-------------+                       +-----------v-------------+
         | CameraWorkerSupervisor  |                       | CameraWorkerSupervisor  |
         |       (Camera 1)        |                       |       (Camera N)        |
         +-----------+-------------+                       +-----------+-------------+
                     | (mp.Process)                                    | (mp.Process)
         +-----------v-------------+                       +-----------v-------------+
         |   Isolated OS Worker    |                       |   Isolated OS Worker    |
         |  (Decode / Ingestion)   |                       |  (Decode / Ingestion)   |
         +-------------------------+                       +-------------------------+
```

* **Dynamic Camera Lifecycle:** Supports `add_camera()`, `remove_camera()`, `start_all()`, `stop_all()`, and `read_camera_frame()`.
* **Telemetry Aggregation:** Collects per-camera worker status, restart count, uptime, frames written, and heartbeat timestamps.

### 2.2 CameraStream Integration (`src/camserv/acquisition/camera.py`)
* `StreamConfig.use_process_isolation: bool`: Enables zero-downtime isolated worker execution without altering existing API signatures.
* Seamless `async for frame in stream:` consumption yielding standard `Frame` objects populated directly from the supervised shared memory ring buffer.

---

## 3. Verification & Acceptance Evidence

### 3.1 Test Suite Execution
* `tests/test_camera_stream_isolation.py`:
  - `test_camera_stream_with_process_isolation_streaming`: Verified asynchronous frame streaming over isolated worker.
  - `test_camera_manager_with_isolated_streams`: Verified multi-camera coordination via `CameraManager`.
* `tests/test_ingestion_supervisor.py`:
  - `test_camera_worker_supervisor_lifecycle`: Validated process spawn, frame read, and clean termination.
  - `test_ingestion_manager_multi_camera`: Validated multi-camera registration, simultaneous streaming, and bulk shutdown.

All tests passed with zero failures in automated regression suites.
