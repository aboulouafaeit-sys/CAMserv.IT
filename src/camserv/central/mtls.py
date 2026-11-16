"""
camserv.central.mtls
====================

Zero-Trust Mutual TLS (mTLS) Security Gateway, SAN Identity Binding,
and Active Session Termination upon Quarantine for Multi-Appliance NVR Clusters.
"""

from __future__ import annotations

import hashlib
import ssl
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class NodeCertificateInfo:
    """Represents a validated mTLS identity certificate for a cluster node."""

    node_id: str
    common_name: str
    fingerprint_sha256: str
    issuer: str
    issued_timestamp: float
    expiry_timestamp: float
    san_dns_names: list[str] = field(default_factory=list)
    is_revoked: bool = False
    revocation_reason: str | None = None


class EnterpriseMtlsGateway:
    """
    Validates client certificates, enforces strict SAN/identity matching,
    and manages active session tracking with immediate revocation termination.
    """

    def __init__(self, cluster_ca_fingerprint: str | None = None) -> None:
        self.cluster_ca_fingerprint = cluster_ca_fingerprint
        self.enrolled_certificates: dict[str, NodeCertificateInfo] = {}
        self.revoked_fingerprints: set[str] = set()
        # session_id -> {node_id, fingerprint, connected_at, is_active}
        self.active_sessions: dict[str, dict[str, Any]] = {}

    def enroll_node_certificate(self, cert_info: NodeCertificateInfo) -> bool:
        """Enroll an authorized node's certificate in the trust store."""
        clean_fingerprint = cert_info.fingerprint_sha256.upper().replace(":", "").replace(" ", "")
        if clean_fingerprint in self.revoked_fingerprints:
            logger.warning("mtls.enrollment_rejected_revoked", node=cert_info.node_id)
            return False

        cert_info.fingerprint_sha256 = clean_fingerprint
        self.enrolled_certificates[cert_info.node_id] = cert_info
        logger.info(
            "mtls.node_enrolled",
            node=cert_info.node_id,
            fingerprint=clean_fingerprint,
            common_name=cert_info.common_name,
        )
        return True

    def validate_peer_connection(
        self,
        node_id: str,
        provided_fingerprint: str,
        provided_common_name: str | None = None,
    ) -> tuple[bool, str]:
        """
        Verify peer node mTLS identity, check SAN/CommonName binding,
        and verify against certificate revocation lists.
        """
        clean_fingerprint = provided_fingerprint.upper().replace(":", "").replace(" ", "")

        if clean_fingerprint in self.revoked_fingerprints:
            logger.error("mtls.connection_rejected_revoked_cert", node=node_id)
            return False, "Certificate is REVOKED"

        if node_id not in self.enrolled_certificates:
            logger.warning("mtls.connection_rejected_unregistered_node", node=node_id)
            return False, "Node not registered in cluster trust store"

        expected = self.enrolled_certificates[node_id]
        if expected.is_revoked:
            return False, f"Certificate revoked: {expected.revocation_reason}"

        if clean_fingerprint != expected.fingerprint_sha256:
            logger.error(
                "mtls.fingerprint_mismatch",
                node=node_id,
                expected=expected.fingerprint_sha256,
                actual=clean_fingerprint,
            )
            return False, "Cryptographic certificate fingerprint mismatch"

        if provided_common_name:
            valid_names = {expected.common_name, *expected.san_dns_names}
            if provided_common_name not in valid_names:
                logger.error(
                    "mtls.common_name_mismatch",
                    node=node_id,
                    expected=expected.common_name,
                    provided=provided_common_name,
                )
                return False, f"Identity mismatch: CN '{provided_common_name}' not authorized for node '{node_id}'"

        if time.time() > expected.expiry_timestamp:
            logger.error("mtls.certificate_expired", node=node_id)
            return False, "Node certificate has expired"

        return True, "AUTHORIZED"

    def register_active_session(self, session_id: str, node_id: str, fingerprint: str) -> bool:
        """Register an active authenticated TLS session."""
        ok, _ = self.validate_peer_connection(node_id, fingerprint)
        if not ok:
            return False

        self.active_sessions[session_id] = {
            "session_id": session_id,
            "node_id": node_id,
            "fingerprint": fingerprint.upper().replace(":", "").replace(" ", ""),
            "connected_at": time.time(),
            "is_active": True,
        }
        return True

    def is_session_valid(self, session_id: str) -> bool:
        """Check if an active session remains valid and not revoked."""
        session = self.active_sessions.get(session_id)
        if not session or not session.get("is_active"):
            return False

        node_id = session["node_id"]
        cert = self.enrolled_certificates.get(node_id)
        if not cert or cert.is_revoked:
            session["is_active"] = False
            return False

        if session["fingerprint"] in self.revoked_fingerprints:
            session["is_active"] = False
            return False

        return True

    def revoke_node(self, node_id: str, reason: str = "Administrative Quarantine") -> bool:
        """
        Immediately revoke a node's certificate, ban its fingerprint,
        and terminate all active in-flight authenticated sessions.
        """
        if node_id not in self.enrolled_certificates:
            return False

        cert = self.enrolled_certificates[node_id]
        cert.is_revoked = True
        cert.revocation_reason = reason
        self.revoked_fingerprints.add(cert.fingerprint_sha256)

        # Terminate active sessions for this node immediately
        terminated_count = 0
        for session in self.active_sessions.values():
            if session.get("node_id") == node_id and session.get("is_active"):
                session["is_active"] = False
                session["terminated_at"] = time.time()
                session["termination_reason"] = reason
                terminated_count += 1

        self.last_terminated_sessions_count = terminated_count

        logger.error(
            "mtls.node_certificate_revoked",
            node=node_id,
            reason=reason,
            terminated_sessions=terminated_count,
        )
        return True

    def create_ssl_context(self, verify_mode: ssl.VerifyMode = ssl.CERT_REQUIRED) -> ssl.SSLContext:
        """Create a hardened TLS 1.3/1.2 SSL context for cluster communication."""
        ctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        ctx.verify_mode = verify_mode
        if hasattr(ssl, "OP_NO_TLSv1") and hasattr(ssl, "OP_NO_TLSv1_1"):
            ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        return ctx
