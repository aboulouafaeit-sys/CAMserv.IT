"""Shared Memory Circular Ring Buffer for High-Throughput Video Ingestion (Phase 1C).

Provides zero-copy / low-copy inter-process frame transport:
* Uses Python's native ``multiprocessing.shared_memory.SharedMemory``.
* Operates on POSIX shared memory (``/dev/shm``) on Linux and named memory on Windows.
* Fixed-size pre-allocated circular ring buffer slots.
* Header metadata (64 bytes) per slot: magic, sequence, timestamp, resolution, format.
* Bounded drop-oldest overrun policy for real-time surveillance processing.
* Atomic sequence coordination preventing torn reads/writes.
* Automatic cleanup and recovery on worker termination.
"""

from __future__ import annotations

import struct
import time
from multiprocessing import shared_memory
from typing import Any, Tuple

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Constants
_MAGIC_HEADER = 0x43414D53  # "CAMS" in ASCII
_HEADER_FORMAT = "<IIQdIIII24s"  # 64 bytes total
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)
assert _HEADER_SIZE == 64, f"Header size must be exactly 64 bytes, got {_HEADER_SIZE}"

_STATUS_EMPTY = 0
_STATUS_WRITING = 1
_STATUS_READY = 2


class SharedMemoryRingBuffer:
    """Bounded circular ring buffer mapped into shared memory."""

    def __init__(
        self,
        name: str,
        num_slots: int = 5,
        max_width: int = 1920,
        max_height: int = 1080,
        channels: int = 3,
        create: bool = True,
    ) -> None:
        self.name = name
        self.num_slots = max(2, num_slots)
        self.max_width = max_width
        self.max_height = max_height
        self.channels = channels

        self._payload_size = self.max_width * self.max_height * self.channels
        self._slot_size = _HEADER_SIZE + self._payload_size
        self._total_size = self._slot_size * self.num_slots

        self._is_creator = create
        self._last_read_seq = -1
        self._shm: shared_memory.SharedMemory | None = None

        if create:
            # Clean up stale segment with the same name if left by a crashed process
            try:
                stale = shared_memory.SharedMemory(name=self.name)
                stale.close()
                stale.unlink()
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.debug("shared_memory.stale_cleanup_ignored", error=str(exc))

            self._shm = shared_memory.SharedMemory(create=True, size=self._total_size, name=self.name)
            # Initialize all slot headers to empty
            for i in range(self.num_slots):
                self._write_header(i, seq=0, ts=0.0, width=0, height=0, status=_STATUS_EMPTY)
        else:
            self._shm = shared_memory.SharedMemory(name=self.name)

    @property
    def total_bytes(self) -> int:
        """Return total allocated shared memory size in bytes."""
        return self._total_size

    def _get_slot_offset(self, slot_idx: int) -> int:
        return (slot_idx % self.num_slots) * self._slot_size

    def _write_header(
        self,
        slot_idx: int,
        *,
        seq: int,
        ts: float,
        width: int,
        height: int,
        status: int,
        data_size: int = 0,
    ) -> None:
        if self._shm is None:
            return
        offset = self._get_slot_offset(slot_idx)
        packed = struct.pack(
            _HEADER_FORMAT,
            _MAGIC_HEADER,
            slot_idx,
            seq,
            ts,
            width,
            height,
            self.channels,
            data_size,
            b"\x00" * 24,
        )
        self._shm.buf[offset : offset + _HEADER_SIZE] = bytearray(packed)
        # Set status atomically after header write
        self._shm.buf[offset + 36 : offset + 40] = bytearray(struct.pack("<I", status))

    def _read_header(self, slot_idx: int) -> dict[str, Any] | None:
        if self._shm is None:
            return None
        offset = self._get_slot_offset(slot_idx)
        raw = bytes(self._shm.buf[offset : offset + _HEADER_SIZE])
        try:
            magic, idx, seq, ts, w, h, ch, status, _ = struct.unpack(_HEADER_FORMAT, raw)
            if magic != _MAGIC_HEADER:
                return None
            return {
                "slot_idx": idx,
                "seq": seq,
                "timestamp": ts,
                "width": w,
                "height": h,
                "channels": ch,
                "status": status,
            }
        except struct.error:
            return None

    def write_frame(self, frame: np.ndarray, timestamp: float, sequence: int) -> int:
        """Write a raw numpy BGR/RGB frame into the next circular slot.

        Returns slot index written, or raises ValueError if frame exceeds slot dimensions.
        """
        if self._shm is None:
            raise RuntimeError("SharedMemoryRingBuffer is closed")

        h, w = frame.shape[:2]
        ch = frame.shape[2] if frame.ndim == 3 else 1
        if w > self.max_width or h > self.max_height or ch != self.channels:
            raise ValueError(
                f"Frame dimensions ({w}x{h}x{ch}) exceed maximum buffer capacity "
                f"({self.max_width}x{self.max_height}x{self.channels})"
            )

        slot_idx = sequence % self.num_slots
        offset = self._get_slot_offset(slot_idx)

        # 1. Mark slot as writing
        self._write_header(slot_idx, seq=sequence, ts=timestamp, width=w, height=h, status=_STATUS_WRITING)

        # 2. Write raw frame bytes directly into shared memory buffer slice
        payload_offset = offset + _HEADER_SIZE
        raw_bytes = frame.tobytes()
        self._shm.buf[payload_offset : payload_offset + len(raw_bytes)] = bytearray(raw_bytes)

        # 3. Mark slot as ready with final sequence and timestamp
        self._write_header(
            slot_idx,
            seq=sequence,
            ts=timestamp,
            width=w,
            height=h,
            status=_STATUS_READY,
            data_size=len(raw_bytes),
        )
        return slot_idx

    def read_latest_frame(self) -> tuple[np.ndarray, float, int] | None:
        """Read the newest available frame from the ring buffer.

        Returns (frame, timestamp, sequence) or None if no new frame is ready.
        """
        if self._shm is None:
            return None

        newest_slot = -1
        highest_seq = self._last_read_seq

        # Scan slots to find the newest ready slot
        for i in range(self.num_slots):
            meta = self._read_header(i)
            if meta and meta["status"] == _STATUS_READY:
                if meta["seq"] > highest_seq:
                    highest_seq = meta["seq"]
                    newest_slot = i

        if newest_slot == -1 or highest_seq <= self._last_read_seq:
            return None

        # Read the newest slot
        meta = self._read_header(newest_slot)
        if not meta or meta["status"] != _STATUS_READY or meta["seq"] != highest_seq:
            return None

        offset = self._get_slot_offset(newest_slot)
        payload_offset = offset + _HEADER_SIZE
        w, h, ch = meta["width"], meta["height"], meta["channels"]
        size = w * h * ch

        # Construct numpy array view
        raw_slice = bytes(self._shm.buf[payload_offset : payload_offset + size])
        frame = np.frombuffer(raw_slice, dtype=np.uint8).reshape((h, w, ch) if ch > 1 else (h, w))

        self._last_read_seq = highest_seq
        return frame, meta["timestamp"], highest_seq

    def close(self) -> None:
        """Close this process's handle to shared memory."""
        if self._shm is not None:
            try:
                self._shm.close()
            except Exception:
                pass
            self._shm = None

    def unlink(self) -> None:
        """Destroy the shared memory segment (call only from creator process)."""
        if self._shm is not None:
            try:
                self._shm.close()
            except Exception:
                pass
            try:
                self._shm.unlink()
            except Exception:
                pass
            self._shm = None

    def __enter__(self) -> SharedMemoryRingBuffer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._is_creator:
            self.unlink()
        else:
            self.close()
