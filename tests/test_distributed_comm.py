"""
tests.test_distributed_comm
===========================

Unit tests for CAMserv Central secure distributed communication, Ed25519 envelopes,
replay attack prevention, rate limiting, data minimization, and store-and-forward buffering.
"""

import time
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv.central.comm import (
    DataMinimizationViolationError,
    DistributedGateway,
    MessageVerificationError,
    OfflineMessageBuffer,
    PayloadType,
    RateLimitExceededError,
    ReplayAttackError,
    SecureMessageEnvelope,
)


def test_secure_message_envelope_signing_and_verification():
    """Verify Ed25519 message envelope signing, payload hashing, and tamper rejection."""
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    env = SecureMessageEnvelope(
        message_id="msg-001",
        sender_id="appliance-alpha",
        recipient_id="central-hub",
        payload_type=PayloadType.EVENT_ALERT,
        payload_data={"event_id": "EVT-100", "severity": "HIGH", "confidence": 0.94},
    )
    env.sign(priv_key)
    assert env.signature_hex != ""
    assert env.verify(pub_key_hex) is True

    # Tampering with payload data MUST invalidate signature
    env.payload_data["severity"] = "LOW"
    assert env.verify(pub_key_hex) is False


def test_replay_attack_prevention():
    """Verify that reused nonces and stale timestamps are rejected."""
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    gateway = DistributedGateway(node_id="central-hub", max_clock_skew_sec=10.0)

    env1 = SecureMessageEnvelope(
        message_id="msg-101",
        sender_id="appliance-alpha",
        recipient_id="central-hub",
        payload_type=PayloadType.TELEMETRY,
        payload_data={"cpu": 25.0},
        nonce="NONCE_UNIQUE_1",
    )
    env1.sign(priv_key)
    assert gateway.validate_incoming_envelope(env1, pub_key_hex) is True

    # Replay with identical nonce MUST raise ReplayAttackError
    env_replay = SecureMessageEnvelope(
        message_id="msg-102",
        sender_id="appliance-alpha",
        recipient_id="central-hub",
        payload_type=PayloadType.TELEMETRY,
        payload_data={"cpu": 26.0},
        nonce="NONCE_UNIQUE_1",
    )
    env_replay.sign(priv_key)
    with pytest.raises(ReplayAttackError, match="Replay attack detected"):
        gateway.validate_incoming_envelope(env_replay, pub_key_hex)

    # Stale timestamp (> 10s skew) MUST raise ReplayAttackError
    env_stale = SecureMessageEnvelope(
        message_id="msg-103",
        sender_id="appliance-alpha",
        recipient_id="central-hub",
        payload_type=PayloadType.TELEMETRY,
        payload_data={"cpu": 25.0},
        timestamp=time.time() - 30.0,
        nonce="NONCE_UNIQUE_2",
    )
    env_stale.sign(priv_key)
    with pytest.raises(ReplayAttackError, match="Clock skew exceeded"):
        gateway.validate_incoming_envelope(env_stale, pub_key_hex)


def test_rate_limiter_exceeded():
    """Verify that excessive message volume from a single sender is throttled."""
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    gateway = DistributedGateway(node_id="central-hub", rate_limit_per_minute=3)

    for i in range(3):
        env = SecureMessageEnvelope(
            message_id=f"msg-rate-{i}",
            sender_id="flooding-node",
            recipient_id="central-hub",
            payload_type=PayloadType.TELEMETRY,
            payload_data={"counter": i},
        )
        env.sign(priv_key)
        assert gateway.validate_incoming_envelope(env, pub_key_hex) is True

    # 4th message exceeds limit of 3 msgs/min
    env4 = SecureMessageEnvelope(
        message_id="msg-rate-4",
        sender_id="flooding-node",
        recipient_id="central-hub",
        payload_type=PayloadType.TELEMETRY,
        payload_data={"counter": 4},
    )
    env4.sign(priv_key)
    with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
        gateway.validate_incoming_envelope(env4, pub_key_hex)


def test_data_minimization_enforcement():
    """Verify that raw unmasked video fields are forbidden over WAN transport."""
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key_hex = priv_key.public_key().public_bytes_raw().hex()

    gateway = DistributedGateway(node_id="central-hub")

    # Legal payload: Alert metadata + SHA-256 manifest hash
    legal_env = SecureMessageEnvelope(
        message_id="msg-legal",
        sender_id="appliance-alpha",
        recipient_id="central-hub",
        payload_type=PayloadType.EVENT_ALERT,
        payload_data={"event_id": "EVT-1", "manifest_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    )
    legal_env.sign(priv_key)
    assert gateway.validate_incoming_envelope(legal_env, pub_key_hex) is True

    # Illegal payload: Attempting to leak raw video
    illegal_env = SecureMessageEnvelope(
        message_id="msg-illegal",
        sender_id="appliance-alpha",
        recipient_id="central-hub",
        payload_type=PayloadType.EVENT_ALERT,
        payload_data={"event_id": "EVT-2", "raw_frame": "BASE64_BYTES_REPRESENTATION_OF_UNMASKED_FACE"},
    )
    illegal_env.sign(priv_key)
    with pytest.raises(DataMinimizationViolationError, match="DATA MINIMIZATION VIOLATION"):
        gateway.validate_incoming_envelope(illegal_env, pub_key_hex)


def test_offline_store_and_forward_buffer():
    """Verify store-and-forward queue behavior during network disconnection."""
    buffer = OfflineMessageBuffer(max_capacity=5)

    msgs = []
    for i in range(3):
        m = SecureMessageEnvelope(
            message_id=f"buf-msg-{i}",
            sender_id="edge-node-1",
            recipient_id="central-hub",
            payload_type=PayloadType.EVENT_ALERT,
            payload_data={"idx": i},
        )
        buffer.enqueue(m)
        msgs.append(m)

    assert buffer.get_pending_count() == 3

    # Dequeue batch of 2
    batch = buffer.dequeue_batch(batch_size=2)
    assert len(batch) == 2
    assert batch[0].message_id == "buf-msg-0"
    assert batch[1].message_id == "buf-msg-1"

    # Acknowledge processed
    buffer.acknowledge_batch([b.message_id for b in batch])
    assert buffer.get_pending_count() == 1
    remaining = buffer.dequeue_batch(batch_size=5)
    assert len(remaining) == 1
    assert remaining[0].message_id == "buf-msg-2"
