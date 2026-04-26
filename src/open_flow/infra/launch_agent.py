"""Register / unregister the Open Flow LaunchAgent for login auto-start.

Only acts when the app is running from /Applications — skips silently
during development so we don't pollute the developer's login items.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_LABEL = "com.openflow.app"
_APP_PATH = Path("/Applications/Open Flow.app")
_BINARY   = _APP_PATH / "Contents" / "MacOS" / "Open Flow"
_PLIST    = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{home}/Library/Logs/OpenFlow.log</string>
    <key>StandardErrorPath</key>
    <string>{home}/Library/Logs/OpenFlow.log</string>
</dict>
</plist>
"""


def _running_from_applications() -> bool:
    import sys
    return sys.executable.startswith(str(_APP_PATH))


def register() -> None:
    """Write the LaunchAgent plist. No-op outside /Applications.

    We deliberately do NOT call `launchctl load` here. Combined with
    `RunAtLoad=true` in the plist, that would immediately spawn a second
    instance of Open Flow on top of the running one — which has been seen
    to surface as a duplicate onboarding wizard. Files written to
    `~/Library/LaunchAgents` are picked up automatically by launchd at the
    user's next login, which is exactly the auto-start behaviour we want.
    """
    if not _running_from_applications():
        logger.debug("LaunchAgent: skipped (not running from /Applications)")
        return

    if not _BINARY.exists():
        logger.warning("LaunchAgent: binary not found at %s", _BINARY)
        return

    _PLIST.parent.mkdir(parents=True, exist_ok=True)
    _PLIST.write_text(
        _PLIST_TEMPLATE.format(
            label=_LABEL,
            binary=_BINARY,
            home=Path.home(),
        ),
        encoding="utf-8",
    )
    logger.info("LaunchAgent plist written: %s (loads at next login)", _PLIST)


def unregister() -> None:
    """Unload and remove the LaunchAgent plist."""
    if _PLIST.exists():
        try:
            subprocess.run(["launchctl", "unload", str(_PLIST)], capture_output=True)
        except Exception:
            pass
        _PLIST.unlink(missing_ok=True)
        logger.info("LaunchAgent removed")
