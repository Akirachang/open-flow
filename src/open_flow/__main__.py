"""Entry point — runs onboarding on first launch, then the tray app."""

from __future__ import annotations

import logging
import sys
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
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
        AppHelper.stopEventLoop()

    wizard = OnboardingWizard(cfg, on_complete=_on_complete)
    wizard.run()
    AppHelper.runEventLoop()

    if not completed.is_set():
        sys.exit(0)


if __name__ == "__main__":
    main()
