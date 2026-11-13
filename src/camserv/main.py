"""
camserv.main
============

Unified Command-Line Interface and Production Runtime Entrypoint for the
CAMserv Advanced Security Intelligence Platform.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog
import uvicorn

from camserv.acquisition.onvif import DeploymentTopology, NVRCompatibilityTester, ONVIFDiscovery
from camserv.api.app import create_app
from camserv.config.settings import get_settings
from camserv.platform.hardware import HardwareDetector
from camserv.security.audit import AuditLogger
from camserv.storage.forensics import IndependentVerifier

logger = structlog.get_logger(__name__)


def run_serve(args: argparse.Namespace) -> int:
    """Launch the CAMserv API and analytics processing engine."""
    settings = get_settings()
    host = args.host or settings.api.host
    port = args.port or settings.api.port

    logger.info("camserv.cli.starting_server", host=host, port=port)
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def run_verify_evidence(args: argparse.Namespace) -> int:
    """Independently audit an exported evidence ZIP archive."""
    pkg_path = Path(args.package)
    if not pkg_path.exists():
        print(f"Error: Evidence archive '{args.package}' not found.", file=sys.stderr)
        return 1

    trusted_key = None
    if args.public_key:
        key_path = Path(args.public_key)
        if key_path.exists():
            trusted_key = key_path.read_text(encoding="utf-8")
        else:
            print(f"Warning: Public key file '{args.public_key}' not found; using embedded key.", file=sys.stderr)

    print(f"\n[CAMserv Independent Forensic Auditor] Verifying: {args.package}")
    print("-" * 70)

    result = IndependentVerifier.verify_package(pkg_path, trusted_public_key_pem=trusted_key)

    print(f"Evidence ID:          {result.package_id}")
    print(f"Source Camera:        {result.camera_id}")
    print(f"Timestamp (UTC):      {result.timestamp_utc}")
    print(f"Files Verified:       {len(result.files_checked)} payload items")
    print(f"File Hash Integrity:  {'PASS' if result.manifest_hash_match else 'FAIL (TAMPER DETECTED)'}")
    print(f"Ed25519 Signature:    {'AUTHENTIC' if result.signature_valid else 'INVALID / FORGED'}")
    print(f"Chain of Custody:     {'INTACT' if result.chain_of_custody_intact else 'BROKEN'}")
    print("-" * 70)
    print(f"Status Details:       {result.details}")
    print("=" * 70)

    if result.is_valid:
        print("VERIFICATION RESULT: ACCEPTED — Forensic integrity confirmed.\n")
        return 0
    else:
        print("VERIFICATION RESULT: REJECTED — Evidence has been tampered with or corrupted.\n")
        return 2


def run_detect_hw(args: argparse.Namespace) -> int:
    """Profile host compute capabilities and recommended backend."""
    print("\n[CAMserv Hardware Diagnostic Prober]")
    print("-" * 70)
    profile = HardwareDetector.probe_host()
    summary = profile.summary()

    for k, v in summary.items():
        if isinstance(v, list):
            print(f"{k.replace('_', ' ').title()}:")
            for item in v:
                print(f"  - {item}")
        else:
            print(f"{k.replace('_', ' ').title():<26}: {v}")

    print("-" * 70)
    print(f"CUDA Available:           {profile.has_cuda}")
    print(f"TensorRT Available:       {profile.has_tensorrt}")
    print(f"Recommended Backend:      {profile.recommended_backend.upper()}")
    print("=" * 70 + "\n")
    return 0


def run_nvr_scan(args: argparse.Namespace) -> int:
    """Discover ONVIF cameras and test endpoint compatibility."""
    print("\n[CAMserv ONVIF & NVR Interoperability Scanner]")
    print("-" * 70)

    async def _async_scan() -> None:
        if args.url:
            print(f"Testing target endpoint: {args.url}")
            report = await NVRCompatibilityTester.test_endpoint(
                rtsp_url=args.url,
                topology=DeploymentTopology.TOPOLOGY_A_NVR_INTERCONNECT,
            )
            print(f"Host:                 {report.target_host}")
            print(f"Handshake Latency:    {report.handshake_latency_ms} ms")
            print(f"Supported Codecs:     {', '.join(report.supported_codecs)}")
            print(f"Stability Score:      {report.stream_stability_score * 100:.1f}%")
            print("Notes:")
            for n in report.notes:
                print(f"  * {n}")
        else:
            print("Broadcasting ONVIF WS-Discovery probe across local subnet...")
            devices = await ONVIFDiscovery.discover(timeout_sec=args.timeout)
            if not devices:
                print("No ONVIF cameras responded within timeout window.")
                print("Note: In virtual or cloud environments, UDP multicast (239.255.255.250:3702) may be blocked.")
            else:
                print(f"Discovered {len(devices)} ONVIF endpoints:")
                for i, d in enumerate(devices, start=1):
                    print(f"  [{i}] {d.manufacturer} {d.model} @ {d.ip_address} ({d.xaddrs})")

    asyncio.run(_async_scan())
    print("=" * 70 + "\n")
    return 0


def run_audit_verify(args: argparse.Namespace) -> int:
    """Verify cryptographic hash chaining on audit trail logs."""
    log_file = Path(args.log or "logs/audit.jsonl")
    print(f"\n[CAMserv Cryptographic Audit Verifier] Checking: {log_file}")
    print("-" * 70)

    if not log_file.exists():
        print(f"Notice: Audit log file '{log_file}' does not exist yet. No entries to verify.")
        return 0

    auditor = AuditLogger(log_path=log_file)
    valid, count, errors = auditor.verify_integrity()

    if valid:
        print(f"AUDIT CHAIN INTEGRITY: 100% VALID — {count} entries verified. Zero tampering detected in cryptographic hash sequence.")
        return 0
    else:
        print(f"AUDIT CHAIN INTEGRITY: CORRUPTED — Hash mismatch detected. Errors: {errors}")
        return 3


def main() -> None:
    """Main CLI parser and dispatcher."""
    parser = argparse.ArgumentParser(
        prog="camserv",
        description="CAMserv Advanced Security Intelligence Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational Subcommands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start CAMserv API and Analytics Server")
    serve_parser.add_argument("--host", type=str, default=None, help="Host interface to bind")
    serve_parser.add_argument("--port", type=int, default=None, help="Port to listen on")

    # verify-evidence
    ev_parser = subparsers.add_parser("verify-evidence", help="Verify forensic evidence package")
    ev_parser.add_argument("package", type=str, help="Path to evidence .zip file")
    ev_parser.add_argument("--public-key", type=str, default=None, help="Path to trusted Ed25519 PEM public key")

    # detect-hw
    subparsers.add_parser("detect-hw", help="Probe host CPU, RAM, and GPU accelerator capabilities")

    # nvr-scan
    nvr_parser = subparsers.add_parser("nvr-scan", help="Scan local network for ONVIF cameras or test RTSP URL")
    nvr_parser.add_argument("--url", type=str, default=None, help="Specific RTSP endpoint to test")
    nvr_parser.add_argument("--timeout", type=float, default=2.0, help="Multicast discovery timeout in seconds")

    # audit-verify
    audit_parser = subparsers.add_parser("audit-verify", help="Verify cryptographic hash chain of audit logs")
    audit_parser.add_argument("--log", type=str, default=None, help="Path to audit.jsonl log file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "serve": run_serve,
        "verify-evidence": run_verify_evidence,
        "detect-hw": run_detect_hw,
        "nvr-scan": run_nvr_scan,
        "audit-verify": run_audit_verify,
    }

    handler = dispatch.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
