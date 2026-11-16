"""
camserv.desktop
===============

CAMserv Desktop Operator Console for Windows 11.
Provides a modern, responsive, decoupled GUI client for security operators,
connecting to the background CAMserv Windows Service via authenticated REST/WebSocket.
"""

from camserv.desktop.client import DesktopServiceClient
from camserv.desktop.console import DesktopOperatorConsole

__all__ = ["DesktopServiceClient", "DesktopOperatorConsole"]
