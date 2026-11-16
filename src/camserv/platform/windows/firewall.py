"""
camserv.platform.windows.firewall
=================================

Windows Defender Firewall rule management for CAMserv network services.
Ensures ports required for RTSP (554/8554), ONVIF discovery (3702), and REST/WS (8080)
can receive inbound camera traffic without disabling the system firewall.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import structlog

logger = structlog.get_logger(__name__)


class WindowsFirewallManager:
    """Configures specific, least-privilege Windows Defender Firewall rules."""

    def __init__(self) -> None:
        self._netsh = shutil.which("netsh.exe") or "netsh.exe"

    def _run_netsh(self, *args: str) -> tuple[int, str]:
        if os.name != "nt":
            return 0, "Non-windows host; skipping firewall rule."
        try:
            res = subprocess.run(
                [self._netsh, "advfirewall", "firewall", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=10,
            )
            return res.returncode, res.stdout.strip()
        except Exception as exc:
            return 1, str(exc)

    def add_inbound_port_rule(
        self,
        rule_name: str,
        port: int,
        protocol: str = "TCP",
        description: str = "",
    ) -> bool:
        """Allow inbound traffic on a specific port for CAMserv services."""
        cmd = [
            "add",
            "rule",
            f"name={rule_name}",
            "dir=in",
            "action=allow",
            f"protocol={protocol.upper()}",
            f"localport={port}",
            f"description={description or rule_name}",
        ]
        code, out = self._run_netsh(*cmd)
        if code == 0:
            logger.info("windows.firewall.rule_added", rule=rule_name, port=port)
            return True
        else:
            logger.debug("windows.firewall.rule_warning", rule=rule_name, output=out)
            return False

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a previously registered firewall rule."""
        cmd = ["delete", "rule", f"name={rule_name}"]
        code, out = self._run_netsh(*cmd)
        return code == 0

    def configure_camserv_default_rules(self) -> dict[str, bool]:
        """Configure standard rules for CAMserv Web API and NVR streaming."""
        results = {
            "api_web": self.add_inbound_port_rule("CAMserv Web API", 8080, "TCP", "CAMserv Web and REST API"),
            "rtsp_tcp": self.add_inbound_port_rule("CAMserv RTSP TCP", 8554, "TCP", "CAMserv RTSP stream ingestion"),
            "onvif_discovery": self.add_inbound_port_rule("CAMserv ONVIF Discovery", 3702, "UDP", "WS-Discovery probes"),
        }
        return results
