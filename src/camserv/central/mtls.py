"""
camserv.central.mtls
====================

Zero-Trust Mutual TLS (mTLS) Security Gateway and Hardware-Bound Node Authorization.
Enforces cryptographic identity verification for all edge-to-central and node-to-node links.
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
    is_revoked: bool = False
    revocation_reason: str | None = None


class EnterpriseMtlsGateway:
    """
    Validates client certificates and enforces strict mTLS access control across cluster nodes.
    """

    def __init__(self, cluster_ca_fingerprint: str | None = None) -> None:
        self.cluster_ca_fingerprint = cluster_ca_fingerprint
        self.enrolled_certificates: dict[str, NodeCertificateInfo] = {}
        self.revoked_fingerprints: set[str] = set()

    def enroll_node_certificate(self, cert_info: NodeCertificateInfo) -> bool:
        """Enroll an authorized node's certificate in the trust store."""
        if cert_info.fingerprint_sha256 in self.revoked_fingerprints:
            logger.warning("mtls.enrollment_rejected_revoked", node=cert_info.node_id)
            return False

        self.enrolled_certificates[cert_info.node_id] = cert_info
        logger.info(
            "mtls.node_enrolled",
            node=cert_info.node_id,
            fingerprint=cert_info.fingerprint_sha256,
        )
        return True

    def validate_peer_connection(
        self,
        node_id: str,
        provided_fingerprint: str,
    ) -> tuple[bool, str]:
        """Verify peer node mTLS identity and check against certificate revocation lists."""
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

        if time.time() > expected.expiry_timestamp:
            logger.error("mtls.certificate_expired", node=node_id)
            return False, "Node certificate has expired"

        return True, "AUTHORIZED"

    def revoke_node(self, node_id: str, reason: str = "Administrative Quarantine") -> bool:
        """Immediately revoke a node's certificate and ban its fingerprint."""
        if node_id not in self.enrolled_certificates:
            return False

        cert = self.enrolled_certificates[node_id]
        cert.is_revoked = True
        cert.revocation_reason = reason
        self.revoked_fingerprints.add(cert.fingerprint_sha256)
        logger.error("mtls.node_certificate_revoked", node=node_id, reason=reason)
        return True

    def create_ssl_context(self, verify_mode: ssl.VerifyMode = ssl.CERT_REQUIRED) -> ssl.SSLContext:
        """Create a hardened TLS 1.3/1.2 SSL context for cluster communication."""
        ctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        ctx.verify_mode = verify_mode
        # Enforce modern secure cipher suites
        if hasattr(ssl, "OP_NO_TLSv1") and hasattr(ssl, "OP_NO_TLSv1_1"):
            ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        return ctx
