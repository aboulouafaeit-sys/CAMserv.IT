"""
camserv.desktop.main
====================

Entry point for the CAMserv Desktop Operator Console.
"""

from __future__ import annotations

import sys
from camserv.desktop.console import DesktopOperatorConsole


def main() -> int:
    app = DesktopOperatorConsole(headless=False)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
