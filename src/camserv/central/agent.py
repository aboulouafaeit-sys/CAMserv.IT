"""
camserv.central.agent
=====================

CAMserv Central Management Gateway Agent.
Runs on the edge appliance to report device health, telemetry, camera catalogs,
and sync recording manifests with the enterprise central management plane.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

import structlog

from camserv.central.sync import EdgeSyncClient
from camserv.platform.hardware import HardwareDetector
from camserv.storage.sqlite_store import SQLiteStore

logger = structlog.get_logger(__name__)


class CentralApplianceAgent:
    """Edge agent orchestrating telemetry and manifest sync with central management."""

    def __init__(
        self,
        appliance_id: str = "appliance-default",
        site_id: str = "site-local",
        tenant_id: str = "default",
        poll_interval_sec: float = 30.0,
        db_path: Path | str | None = None,
    ) -> None:
        self.appliance_id = appliance_id
        self.site_id = site_id
        self.tenant_id = tenant_id
        self.poll_interval_sec = poll_interval_sec

        if db_path is None:
            db_candidates = [
                Path("/var/lib/camserv/db/camserv.db"),
                Path("data/db/camserv.db"),
                Path("data/camserv.db"),
            ]
            for p in db_candidates:
                if p.exists():
                    db_path = p
                    break
            if db_path is None:
                db_path = Path("/var/lib/camserv/db/camserv.db")

        self.db_path = Path(db_path)
        self.store = SQLiteStore(db_path=self.db_path)
        self.running = False
        self._sync_client = EdgeSyncClient(
            appliance_id=self.appliance_id,
            site_id=self.site_id,
            store=self.store,
            tenant_id=self.tenant_id,
        )

    def run(self) -> None:
        """Start the agent main telemetry and heartbeat loop."""
        self.running = True
        logger.info(
            "central.agent.started",
            appliance_id=self.appliance_id,
            site_id=self.site_id,
            poll_interval=self.poll_interval_sec,
        )

        def _handle_exit(sig: int, frame: Any) -> None:
            logger.info("central.agent.shutting_down", signal=sig)
            self.running = False

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

        while self.running:
            try:
                self.sync_cycle()
            except Exception as e:
                logger.error("central.agent.sync_failed", error=str(e))

            # Sleep in short increments for responsive shutdown
            slept = 0.0
            while self.running and slept < self.poll_interval_sec:
                time.sleep(0.5)
                slept += 0.5

        logger.info("central.agent.stopped")

    def sync_cycle(self) -> dict[str, Any]:
        """Perform a single telemetry and manifest check cycle."""
        telemetry = HardwareDetector.probe_host().summary()

        cameras: list[dict[str, Any]] = []
        if self.db_path.exists():
            try:
                store = SQLiteStore(db_path=self.db_path)
                cameras = store.list_cameras()
            except Exception as e:
                logger.warning("central.agent.camera_query_failed", error=str(e))

        discovery_envelope = self._sync_client.publish_camera_discovery(cameras)

        logger.info(
            "central.agent.heartbeat",
            appliance_id=self.appliance_id,
            cameras_active=len(cameras),
            envelope_id=discovery_envelope.message_id,
        )
        return {
            "appliance_id": self.appliance_id,
            "telemetry": telemetry,
            "cameras_count": len(cameras),
            "envelope_id": discovery_envelope.message_id,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="CAMserv Central Gateway Agent")
    parser.add_argument("--appliance-id", default=os.getenv("CAMSERV_APPLIANCE_ID", "appliance-local"))
    parser.add_argument("--site-id", default=os.getenv("CAMSERV_SITE_ID", "site-primary"))
    parser.add_argument("--tenant-id", default=os.getenv("CAMSERV_TENANT_ID", "default"))
    parser.add_argument("--interval", type=float, default=30.0, help="Poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single sync cycle and exit")

    args = parser.parse_args()
    agent = CentralApplianceAgent(
        appliance_id=args.appliance_id,
        site_id=args.site_id,
        tenant_id=args.tenant_id,
        poll_interval_sec=args.interval,
    )

    if args.once:
        res = agent.sync_cycle()
        print(f"Central sync cycle complete: {res}")
        sys.exit(0)
    else:
        agent.run()


if __name__ == "__main__":
    main()
