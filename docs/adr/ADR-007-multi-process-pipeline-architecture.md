# ADR-007: Multi-Process Pipeline & Zero-Copy IPC Ingestion Architecture
**Status:** ACCEPTED  
**Date:** 2026-11-14  
**Context:** Python's Global Interpreter Lock (GIL) limits single-process concurrency to $\approx 180\text{ FPS}$ aggregate under multi-camera loads. Ingest thread failures currently risk stalling the central `asyncio` event loop.  
**Decision:** Migrate camera stream acquisition to dedicated OS worker subprocesses communicating with the core engine and GPU inference workers via POSIX shared memory ring buffers (`/dev/shm`).  
**Consequences:** Complete process isolation; crash of a video decoder does not affect sibling streams; enables linear multi-core scaling up to 64 camera streams without GIL contention.
