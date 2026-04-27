"""Entry point — runs onboarding on first launch, then the tray app."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path


def _setup_logging() -> None:
    """Send logs to both stderr and ~/Library/Logs/OpenFlow.log.

    Plain `basicConfig` only writes to stderr — which goes nowhere when the
    .app is launched via Finder / `open`, so the log file ends up empty even
    though things are happening. Adding a rotating file handler guarantees
    we always have a transcript to debug from.
    """
    log_dir = Path.home() / "Library" / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "OpenFlow.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stderr = logging.StreamHandler()
    stderr.setFormatter(fmt)
    root.addHandler(stderr)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        # Logging fallback should never crash startup.
        pass


_setup_logging()
logger = logging.getLogger(__name__)

# Module-level reference keeps the lock fd alive for the lifetime of the
# process. flock is released when the fd closes, so this must outlive main().
_LOCK_FD: int | None = None


def _acquire_single_instance_lock() -> bool:
    """Return True if this is the only running Open Flow process.

    Uses an exclusive flock on a file in the user's runtime dir. If another
    instance already holds the lock (e.g. the launchd-spawned copy raced with
    a manual launch), this process should exit quietly so the user never sees
    a second wizard or two duelling tray icons.
    """
    import fcntl

    global _LOCK_FD

    lock_dir = Path.home() / "Library" / "Caches" / "open_flow"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "openflow.lock"
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as exc:
        logger.info("Another Open Flow instance is running (%s) — exiting", exc)
        return False
    _LOCK_FD = fd
    return True


def main() -> None:
    if not _acquire_single_instance_lock():
        sys.exit(0)

    from open_flow.data import config as cfg_module

    cfg = cfg_module.load()

    if not cfg.onboarding_complete:
        _run_onboarding(cfg, cfg_module)

    from open_flow.ui.tray import OpenFlowApp
    OpenFlowApp().run()


def _run_onboarding(cfg, cfg_module) -> None:
    """Show the first-run wizard and block until it's finished or cancelled."""
    from AppKit import NSApplication
    from PyObjCTools import AppHelper

    from open_flow.ui.onboarding import OnboardingWizard

    NSApplication.sharedApplication().setActivationPolicy_(1)  # accessory

    completed = threading.Event()

    def _on_complete() -> None:
        cfg.onboarding_complete = True
        cfg_module.save(cfg)
        completed.set()
        from open_flow.infra import launch_agent
        launch_agent.register()
        AppHelper.stopEventLoop()

    wizard = OnboardingWizard(cfg, on_complete=_on_complete)
    wizard.run()
    AppHelper.runEventLoop()

    if not completed.is_set():
        sys.exit(0)


if __name__ == "__main__":
    main()
