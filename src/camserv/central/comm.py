"""
camserv.central.comm
====================

Secure distributed communication layer between CAMserv Central and edge appliances.
Provides Ed25519-signed message envelopes, cryptographic replay protection,
rate limiting, WAN data minimization policy, and persistent offline store-and-forward buffering.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = structlog.get_logger(__name__)


class ReplayAttackError(PermissionError):
    """Raised when a message contains an expired timestamp or a reused nonce."""


class MessageVerificationError(PermissionError):
    """Raised when cryptographic envelope signature or payload integrity fails."""


class RateLimitExceededError(PermissionError):
    """Raised when a device exceeds maximum permitted messages per time window."""


class DataMinimizationViolationError(ValueError):
    """Raised when an attempt is made to transmit raw unmasked video over WAN."""


class PayloadType:
    TELEMETRY = "telemetry"
    EVENT_ALERT = "event_alert"
    MANIFEST_DIGEST = "manifest_digest"
    CONFIG_UPDATE = "config_update"
    COMMAND = "command"
    COMMAND_ACK = "command_ack"


@dataclass(slots=True)
class SecureMessageEnvelope:
    """Tamper-evident cryptographically bound distributed message envelope."""

    message_id: str
    sender_id: str
    recipient_id: str
    payload_type: str
    payload_data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex)
    signature_hex: str = ""

    def compute_signing_bytes(self) -> bytes:
        """Compute canonical serialized bytes for Ed25519 signing and verification."""
        # Canonical hash of the payload_data to bind payload without JSON formatting ambiguity
        payload_canonical = json.dumps(self.payload_data, sort_keys=True)
        payload_hash = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()

        canonical_str = (
            f"MSG_V1|{self.message_id}|{self.sender_id}|{self.recipient_id}|"
            f"{self.payload_type}|{int(self.timestamp)}|{self.nonce}|{payload_hash}"
        )
        return canonical_str.encode("utf-8")

    def sign(self, private_key: ed25519.Ed25519PrivateKey) -> None:
        """Sign envelope with sender's Ed25519 private key."""
        sig = private_key.sign(self.compute_signing_bytes())
        self.signature_hex = sig.hex()

    def verify(self, public_key_hex: str) -> bool:
        """Verify envelope signature with sender's Ed25519 public key."""
        if not self.signature_hex:
            return False
        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
            pub_key.verify(bytes.fromhex(self.signature_hex), self.compute_signing_bytes())
            return True
        except Exception as e:
            logger.warning("comm.signature_verification_failed", error=str(e), msg_id=self.message_id)
            return False


class DistributedGateway:
    """
    Gateway receiver validating incoming message envelopes, enforcing replay protection,
    rate limits, and WAN data minimization policies.
    """

    def __init__(
        self,
        node_id: str,
        max_clock_skew_sec: float = 60.0,
        rate_limit_per_minute: int = 120,
    ) -> None:
        self.node_id = node_id
        self.max_clock_skew_sec = max_clock_skew_sec
        self.rate_limit_per_minute = rate_limit_per_minute
        self._seen_nonces: dict[str, float] = {}  # nonce -> expiry timestamp
        self._rate_counters: dict[str, list[float]] = {}  # sender_id -> timestamps

    def validate_incoming_envelope(self, envelope: SecureMessageEnvelope, sender_public_key_hex: str) -> bool:
        """
        Validate incoming envelope against replay attacks, clock skew, rate limits,
        and data minimization rules.
        """
        now = time.time()

        # 1. Clock skew check (prevent old replayed messages)
        if abs(now - envelope.timestamp) > self.max_clock_skew_sec:
            logger.error("comm.clock_skew_exceeded", msg_time=envelope.timestamp, now=now)
            raise ReplayAttackError(
                f"Clock skew exceeded: Message timestamp ({envelope.timestamp}) differs by > {self.max_clock_skew_sec}s."
            )

        # 2. Cryptographic signature check FIRST
        # Enforces identity verification before updating rate limit counters,
        # preventing unauthenticated DoS attacks that exhaust legitimate senders' quotas.
        if not envelope.verify(sender_public_key_hex):
            raise MessageVerificationError("Cryptographic signature verification failed on message envelope.")

        # 3. Data minimization validation
        self._validate_data_minimization(envelope)

        # 4. Nonce replay check
        self._prune_nonces(now)
        if envelope.nonce in self._seen_nonces:
            logger.error("comm.replay_attack_detected", nonce=envelope.nonce, msg_id=envelope.message_id)
            raise ReplayAttackError(f"Replay attack detected: Nonce '{envelope.nonce}' has already been processed.")

        # 5. Rate limiting check (authenticated senders only)
        self._check_rate_limit(envelope.sender_id, now)

        # Record nonce in sliding cache
        self._seen_nonces[envelope.nonce] = now + (self.max_clock_skew_sec * 2.0)
        return True

    def _validate_data_minimization(self, envelope: SecureMessageEnvelope) -> None:
        """Ensure no raw binary video or unmasked pristine frames are transmitted."""
        payload = envelope.payload_data
        # Bar raw image buffers or large base64 strings in distributed messages
        for key in ("raw_video", "raw_frame", "unmasked_stream", "raw_image"):
            if key in payload:
                raise DataMinimizationViolationError(
                    f"DATA MINIMIZATION VIOLATION: Field '{key}' is strictly forbidden over WAN communication. "
                    "Only event metadata, alert telemetry, and cryptographic SHA-256 manifests are allowed."
                )

    def _check_rate_limit(self, sender_id: str, now: float) -> None:
        """Sliding-window rate limiter per sender."""
        window_start = now - 60.0
        timestamps = self._rate_counters.setdefault(sender_id, [])
        self._rate_counters[sender_id] = [t for t in timestamps if t >= window_start]

        if len(self._rate_counters[sender_id]) >= self.rate_limit_per_minute:
            raise RateLimitExceededError(
                f"Rate limit exceeded: Sender '{sender_id}' sent > {self.rate_limit_per_minute} msgs/min."
            )
        self._rate_counters[sender_id].append(now)

    def _prune_nonces(self, now: float) -> None:
        """Prune expired nonces from cache."""
        expired = [nonce for nonce, exp in self._seen_nonces.items() if exp < now]
        for n in expired:
            del self._seen_nonces[n]


class OfflineMessageBuffer:
    """
    Store-and-forward message buffer for edge appliances.
    Persists messages in local queue during network disconnection and flushes in order
    upon reconnection, without impacting local video recording or vault storage.
    """

    def __init__(self, max_capacity: int = 10000) -> None:
        self.max_capacity = max_capacity
        self._queue: list[SecureMessageEnvelope] = []
        self._processed_ids: set[str] = set()

    def enqueue(self, envelope: SecureMessageEnvelope) -> bool:
        """Enqueue message for delivery."""
        if len(self._queue) >= self.max_capacity:
            # Drop oldest non-critical telemetry if queue is saturated, preserving alerts
            if self._queue[0].payload_type == PayloadType.TELEMETRY:
                dropped = self._queue.pop(0)
                logger.warning("comm.buffer_overflow_dropped_telemetry", msg_id=dropped.message_id)
            else:
                logger.error("comm.buffer_full_cannot_enqueue", msg_id=envelope.message_id)
                return False

        self._queue.append(envelope)
        return True

    def get_pending_count(self) -> int:
        """Return number of queued pending messages."""
        return len(self._queue)

    def dequeue_batch(self, batch_size: int = 50) -> list[SecureMessageEnvelope]:
        """Fetch next batch of messages to dispatch."""
        return self._queue[:batch_size]

    def acknowledge_batch(self, message_ids: list[str]) -> None:
        """Acknowledge successful transmission and remove from queue."""
        id_set = set(message_ids)
        self._queue = [msg for msg in self._queue if msg.message_id not in id_set]
        self._processed_ids.update(id_set)
        # Cap processed cache
        if len(self._processed_ids) > 5000:
            self._processed_ids = set(list(self._processed_ids)[-2500:])
