"""
camserv.central.replication
===========================

Distributed Forensic Replication, Canonical Evidence Serialization, Anti-Replay Attestations,
and Merkle Tree Inclusion Proofs for Multi-Appliance NVR Clusters.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class VerificationVerdict(str, Enum):
    VERIFIED_PRISTINE = "VERIFIED_PRISTINE"
    TAMPER_DETECTED = "TAMPER_DETECTED"
    QUORUM_UNAVAILABLE = "QUORUM_UNAVAILABLE"
    UNREGISTERED_SEGMENT = "UNREGISTERED_SEGMENT"
    REPLAY_ATTACK_DETECTED = "REPLAY_ATTACK_DETECTED"
    TENANT_MISMATCH = "TENANT_MISMATCH"


@dataclass
class EvidenceSealRecord:
    """Represents a finalized cryptographic evidence seal for a video segment."""

    segment_id: str
    camera_id: str
    origin_node_id: str
    sha256_hash: str
    start_timestamp: float
    end_timestamp: float
    frame_count: int
    tenant_id: str = "default"
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex)
    signature: str = ""
    created_at: float = field(default_factory=time.time)

    def compute_canonical_evidence_digest(self) -> str:
        """
        Unambiguous canonical evidence serialization (RFC 8785 style canonical format).
        Domain-separated: CAMSERV-FORENSIC-SEAL-V2
        Eliminates delimiter injection vulnerabilities present in simple concatenation.
        """
        canonical_dict = {
            "schema_version": "v2",
            "domain": "CAMSERV-FORENSIC-SEAL-V2",
            "segment_id": self.segment_id,
            "camera_id": self.camera_id,
            "tenant_id": self.tenant_id,
            "origin_node_id": self.origin_node_id,
            "sha256_hash": self.sha256_hash.upper(),
            "start_timestamp": round(self.start_timestamp, 4),
            "end_timestamp": round(self.end_timestamp, 4),
            "frame_count": int(self.frame_count),
            "nonce": self.nonce,
        }
        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest().upper()

    def compute_seal_digest(self) -> str:
        """Backwards compatible alias for compute_canonical_evidence_digest."""
        return self.compute_canonical_evidence_digest()


@dataclass
class WitnessAttestation:
    """A cryptographic attestation signed by an independent peer witness node."""

    seal_digest: str
    witness_node_id: str
    tenant_id: str = "default"
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex)
    attestation_timestamp: float = field(default_factory=time.time)
    signature: str = ""


class DistributedReplicationEngine:
    """
    Manages peer witness sealing, cross-node evidence verification, anti-replay guards,
    and Merkle tree inclusion proofs.
    """

    def __init__(
        self,
        local_node_id: str,
        tenant_id: str = "default",
        quorum_threshold: int = 2,
        state_dir: Path | str | None = None,
    ) -> None:
        self.local_node_id = local_node_id
        self.tenant_id = tenant_id
        self.quorum_threshold = quorum_threshold
        self.state_dir = Path(state_dir).resolve() if state_dir else None

        # segment_id -> EvidenceSealRecord
        self.primary_seals: dict[str, EvidenceSealRecord] = {}
        # segment_id -> list[WitnessAttestation]
        self.witness_attestations: dict[str, list[WitnessAttestation]] = {}
        # Seen nonces to reject replay attacks: (witness_node_id, nonce)
        self.seen_attestation_nonces: set[tuple[str, str]] = set()
        # Merkle tree leaf hashes (digest -> leaf index)
        self.merkle_leaves: list[str] = []

        if self.state_dir:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        """Durable forensic replay protection: reload seen nonces and primary seals across witness reboots."""
        if not self.state_dir:
            return
        nonces_file = self.state_dir / "seen_nonces.json"
        if nonces_file.exists():
            try:
                raw_nonces = json.loads(nonces_file.read_text(encoding="utf-8"))
                self.seen_attestation_nonces = {tuple(x) for x in raw_nonces}
                logger.info("replication.nonces_restored_from_disk", count=len(self.seen_attestation_nonces))
            except Exception as e:
                logger.error("replication.failed_to_load_nonces", error=str(e))

        seals_file = self.state_dir / "primary_seals.json"
        if seals_file.exists():
            try:
                raw_seals = json.loads(seals_file.read_text(encoding="utf-8"))
                for sid, sdata in raw_seals.items():
                    if isinstance(sdata, dict):
                        seal = EvidenceSealRecord(
                            segment_id=sdata.get("segment_id", sid),
                            camera_id=sdata.get("camera_id", ""),
                            origin_node_id=sdata.get("origin_node_id", ""),
                            sha256_hash=sdata.get("sha256_hash", ""),
                            start_timestamp=float(sdata.get("start_timestamp", 0.0)),
                            end_timestamp=float(sdata.get("end_timestamp", 0.0)),
                            frame_count=int(sdata.get("frame_count", 0)),
                            tenant_id=sdata.get("tenant_id", self.tenant_id),
                            nonce=sdata.get("nonce", ""),
                            signature=sdata.get("signature", ""),
                            created_at=float(sdata.get("created_at", time.time())),
                        )
                        self.primary_seals[sid] = seal
                        self.merkle_leaves.append(seal.compute_canonical_evidence_digest())
                logger.info("replication.seals_restored_from_disk", count=len(self.primary_seals))
            except Exception as e:
                logger.error("replication.failed_to_load_seals", error=str(e))

    def _persist_nonces(self) -> None:
        """Atomically persist seen nonces to disk."""
        if not self.state_dir:
            return
        try:
            tmp_path = self.state_dir / "seen_nonces.json.tmp"
            final_path = self.state_dir / "seen_nonces.json"
            nonce_list = [list(x) for x in self.seen_attestation_nonces]
            tmp_path.write_text(json.dumps(nonce_list, indent=2), encoding="utf-8")
            tmp_path.replace(final_path)
        except Exception as e:
            logger.error("replication.failed_to_persist_nonces", error=str(e))

    def _persist_seals(self) -> None:
        """Atomically persist primary seals to disk."""
        if not self.state_dir:
            return
        try:
            tmp_path = self.state_dir / "primary_seals.json.tmp"
            final_path = self.state_dir / "primary_seals.json"
            seals_dict = {sid: asdict(seal) for sid, seal in self.primary_seals.items()}
            tmp_path.write_text(json.dumps(seals_dict, indent=2), encoding="utf-8")
            tmp_path.replace(final_path)
        except Exception as e:
            logger.error("replication.failed_to_persist_seals", error=str(e))

    def register_evidence_seal(self, seal: EvidenceSealRecord) -> str:
        """Register a new evidence segment seal on the origin node."""
        if seal.tenant_id != self.tenant_id:
            logger.error("replication.tenant_mismatch", seal_tenant=seal.tenant_id, engine_tenant=self.tenant_id)
            raise PermissionError(f"Evidence seal tenant '{seal.tenant_id}' does not match engine tenant '{self.tenant_id}'")

        self.primary_seals[seal.segment_id] = seal
        digest = seal.compute_canonical_evidence_digest()
        self.merkle_leaves.append(digest)
        logger.info(
            "replication.canonical_seal_registered",
            segment_id=seal.segment_id,
            camera_id=seal.camera_id,
            digest=digest,
            nonce=seal.nonce,
        )
        self._persist_seals()
        return digest

    def submit_witness_attestation(self, attestation: WitnessAttestation, segment_id: str) -> bool:
        """Record an independent witness signature with anti-replay protection."""
        if attestation.tenant_id != self.tenant_id:
            logger.warning("replication.attestation_tenant_mismatch", attestation_tenant=attestation.tenant_id)
            return False

        # Anti-replay check: reject duplicate nonces from same witness
        nonce_key = (attestation.witness_node_id, attestation.nonce)
        if nonce_key in self.seen_attestation_nonces:
            logger.error("replication.replay_attack_rejected", witness=attestation.witness_node_id, nonce=attestation.nonce)
            return False

        if segment_id not in self.witness_attestations:
            self.witness_attestations[segment_id] = []

        existing_witnesses = {w.witness_node_id for w in self.witness_attestations[segment_id]}
        if attestation.witness_node_id in existing_witnesses:
            logger.warning("replication.duplicate_witness_rejected", witness=attestation.witness_node_id)
            return False

        self.seen_attestation_nonces.add(nonce_key)
        self._persist_nonces()
        self.witness_attestations[segment_id].append(attestation)
        logger.info(
            "replication.witness_attestation_recorded",
            segment_id=segment_id,
            witness=attestation.witness_node_id,
            total_witnesses=len(self.witness_attestations[segment_id]),
        )
        return True

    def verify_segment_integrity(
        self,
        segment_id: str,
        current_file_bytes: bytes,
        tenant_id: str | None = None,
    ) -> tuple[VerificationVerdict, dict[str, Any]]:
        """
        Cryptographically validates a video segment against local seal and peer witness quorum.
        Detects tampering, frame excision, or unauthorized metadata alteration.
        """
        if segment_id not in self.primary_seals:
            return VerificationVerdict.UNREGISTERED_SEGMENT, {"error": "Segment not registered"}

        seal = self.primary_seals[segment_id]
        effective_tenant = tenant_id or self.tenant_id
        if seal.tenant_id != effective_tenant:
            return VerificationVerdict.TENANT_MISMATCH, {"error": "Cross-tenant evidence access denied"}

        computed_file_hash = hashlib.sha256(current_file_bytes).hexdigest().upper()

        # 1. Verify local file bytes match the original registered seal
        if computed_file_hash != seal.sha256_hash:
            logger.error(
                "replication.tamper_detected.hash_mismatch",
                segment_id=segment_id,
                expected=seal.sha256_hash,
                actual=computed_file_hash,
            )
            return VerificationVerdict.TAMPER_DETECTED, {
                "reason": "Cryptographic file digest mismatch (file was modified on disk)",
                "expected_hash": seal.sha256_hash,
                "actual_hash": computed_file_hash,
            }

        # 2. Check peer witness consensus
        witnesses = self.witness_attestations.get(segment_id, [])
        if len(witnesses) < self.quorum_threshold:
            logger.warning(
                "replication.quorum_warning",
                segment_id=segment_id,
                available=len(witnesses),
                required=self.quorum_threshold,
            )
            return VerificationVerdict.QUORUM_UNAVAILABLE, {
                "reason": f"Witness quorum insufficient ({len(witnesses)}/{self.quorum_threshold})",
                "witness_count": len(witnesses),
            }

        # 3. Verify all witnesses signed the exact same canonical seal digest
        expected_digest = seal.compute_canonical_evidence_digest()
        invalid_witnesses: list[str] = []
        for w in witnesses:
            if w.seal_digest != expected_digest:
                invalid_witnesses.append(w.witness_node_id)

        if invalid_witnesses:
            logger.error(
                "replication.tamper_detected.witness_divergence",
                segment_id=segment_id,
                rogue_witnesses=invalid_witnesses,
            )
            return VerificationVerdict.TAMPER_DETECTED, {
                "reason": "Witness attestation divergence detected",
                "divergent_witnesses": invalid_witnesses,
            }

        return VerificationVerdict.VERIFIED_PRISTINE, {
            "segment_id": segment_id,
            "sha256": computed_file_hash,
            "witness_quorum": len(witnesses),
            "seal_digest": expected_digest,
            "tenant_id": seal.tenant_id,
        }

    def compute_cluster_merkle_root(self) -> str:
        """Computes the root SHA-256 hash across all registered cluster evidence leaves."""
        if not self.merkle_leaves:
            return hashlib.sha256(b"EMPTY_CLUSTER").hexdigest().upper()

        current_layer = list(self.merkle_leaves)
        while len(current_layer) > 1:
            next_layer: list[str] = []
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                right = current_layer[i + 1] if i + 1 < len(current_layer) else left
                combined = f"{left}:{right}".encode("utf-8")
                next_layer.append(hashlib.sha256(combined).hexdigest().upper())
            current_layer = next_layer

        return current_layer[0]

    def generate_inclusion_proof(self, leaf_digest: str) -> list[tuple[str, str]]:
        """
        Generates Merkle inclusion proof path for a specific leaf digest.
        Returns list of (sibling_hash, direction) tuples ('left' or 'right').
        """
        if leaf_digest not in self.merkle_leaves:
            raise KeyError(f"Leaf digest '{leaf_digest}' not in Merkle tree")

        idx = self.merkle_leaves.index(leaf_digest)
        proof: list[tuple[str, str]] = []
        current_layer = list(self.merkle_leaves)

        while len(current_layer) > 1:
            if idx % 2 == 0:
                # Sibling is to the right
                sibling = current_layer[idx + 1] if idx + 1 < len(current_layer) else current_layer[idx]
                proof.append((sibling, "right"))
            else:
                # Sibling is to the left
                sibling = current_layer[idx - 1]
                proof.append((sibling, "left"))

            # Build next layer
            next_layer = []
            for i in range(0, len(current_layer), 2):
                l = current_layer[i]
                r = current_layer[i + 1] if i + 1 < len(current_layer) else l
                next_layer.append(hashlib.sha256(f"{l}:{r}".encode("utf-8")).hexdigest().upper())
            idx = idx // 2
            current_layer = next_layer

        return proof

    @staticmethod
    def verify_inclusion_proof(leaf_digest: str, proof: list[tuple[str, str]], expected_root: str) -> bool:
        """Mathematically verifies that a leaf digest is included in expected_root using the proof path."""
        current = leaf_digest
        for sibling, direction in proof:
            if direction == "right":
                combined = f"{current}:{sibling}".encode("utf-8")
            else:
                combined = f"{sibling}:{current}".encode("utf-8")
            current = hashlib.sha256(combined).hexdigest().upper()
        return current == expected_root
