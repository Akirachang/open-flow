"""Onboarding wizard — warm paper aesthetic with hand-drawn accents.

Step flow (4 steps):
  0  welcome     — keycap hero, hand-drawn arrow, HandUnderline
  1  permissions — three cards with icon badge
  2  models      — download progress for Whisper + LLM
  3  done        — gradient checkmark finish card

Each step lives in a CLWindow-style frame with paper grain, 64px footer
with step dots (left) and buttons (right).
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable

from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSCenterTextAlignment,
    NSColor,
    NSFont,
    NSLeftTextAlignment,
    NSMakeRect,
    NSProgressIndicator,
    NSRightTextAlignment,
    NSScreen,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from open_flow.ui.design import (
    ACCENT, ACCENT_D, ACCENT_W, CARD, GOOD, INK, INK_SOFT, LINE, LINE_STR,
    MUTED, PAPER, PAPER_D, SUBTLE,
    _ButtonBridge,
    apply_grain,
    c,
    hand_arrow,
    hand_underline,
    keycap,
    label,
    make_button,
    rect,
)
from Quartz import CAGradientLayer

logger = logging.getLogger(__name__)

_W, _H = 720, 540
_PAD = 52
_FOOTER_H = 64


def _open_privacy_pane(pane: str) -> None:
    url = f"x-apple.systempreferences:com.apple.preference.security?{pane}"
    try:
        subprocess.Popen(["open", url],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.error("Failed to open privacy pane %s: %s", pane, exc)


def _step_dots(total: int, current: int, cx_left: float, y: float) -> list[NSView]:
    """Row of dots (active = 18×6 pill, inactive = 6×6 circle).
    Returned in order, positioned starting at x=cx_left.
    """
    dots: list[NSView] = []
    x = cx_left
    for i in range(total):
        w = 18 if i == current else 6
        fill = ACCENT if i == current else (*INK_SOFT[:3], 0.20)
        dots.append(rect(x, y, w, 6, color=fill, radius=3))
        x += w + 6
    return dots


class OnboardingWizard:
    STEPS = ["welcome", "permissions", "models", "done"]

    def __init__(self, cfg, on_complete: Callable[[], None]) -> None:
        self._cfg = cfg
        self._on_complete = on_complete
        self._step_index = 0
        self._window: NSWindow | None = None
        self._bridge: _ButtonBridge | None = None
        self._next_tag = 1
        self._progress_bars: list[NSProgressIndicator] = []
        self._status_labels: list[NSTextField] = []
        self._next_btn: NSButton | None = None
        self._download_btn: NSButton | None = None

    # ── Public ───────────────────────────────────────────────────────────

    def run(self) -> None:
        self._build_window()
        self._show_step(0)
        self._window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    # ── Window ───────────────────────────────────────────────────────────

    def _build_window(self) -> None:
        screen = NSScreen.mainScreen()
        sf = screen.frame()
        x = (sf.size.width - _W) / 2
        y = (sf.size.height - _H) / 2

        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, _W, _H), style, NSBackingStoreBuffered, False,
        )
        self._window.setTitle_("Open Flow")
        self._window.setReleasedWhenClosed_(False)
        cv = self._window.contentView()
        cv.setWantsLayer_(True)
        cv.layer().setBackgroundColor_(c(*PAPER).CGColor())
        apply_grain(cv)

        self._bridge = _ButtonBridge.alloc().initWithMap_({})

    def _clear(self) -> None:
        for sub in list(self._window.contentView().subviews()):
            sub.removeFromSuperview()
        self._bridge._map.clear()
        self._next_tag = 1

    def _show_step(self, index: int) -> None:
        self._step_index = index
        self._clear()
        apply_grain(self._window.contentView())
        getattr(self, f"_step_{self.STEPS[index]}")()

    def _next(self) -> None:
        if self._step_index + 1 < len(self.STEPS):
            self._show_step(self._step_index + 1)
        else:
            self._finish()

    def _back(self) -> None:
        if self._step_index > 0:
            self._show_step(self._step_index - 1)

    def _btn(self, title: str, x: float, y: float, w: float, h: float,
             action: Callable, kind: str = "primary",
             enabled: bool = True, size: float = 13) -> NSButton:
        tag = self._next_tag
        self._next_tag += 1
        return make_button(title, x, y, w, h, kind=kind,
                           bridge=self._bridge, tag=tag, action=action,
                           enabled=enabled, size=size)

    def _add(self, view: NSView) -> NSView:
        self._window.contentView().addSubview_(view)
        return view

    def _footer(self, back_action: Callable | None, back_title: str,
                primary_title: str, primary_action: Callable,
                primary_enabled: bool = True) -> None:
        cv = self._window.contentView()
        # Divider
        cv.addSubview_(rect(0, _FOOTER_H, _W, 0.5, color=(*INK_SOFT[:3], 0.12)))
        # Translucent footer bg
        cv.addSubview_(rect(0, 0, _W, _FOOTER_H, color=(1, 1, 1, 0.35)))

        # Step dots — left side
        for d in _step_dots(len(self.STEPS), self._step_index, 24, _FOOTER_H / 2 - 3):
            cv.addSubview_(d)

        # Buttons — right side
        x_right = _W - 24
        primary = self._btn(primary_title, 0, 0, 140, 32,
                            action=primary_action,
                            enabled=primary_enabled, size=13)
        # Measure then reposition
        primary.setFrame_(NSMakeRect(x_right - 140, (_FOOTER_H - 32) / 2,
                                     140, 32))
        cv.addSubview_(primary)
        self._next_btn = primary

        if back_action:
            back = self._btn(back_title,
                             x_right - 140 - 10 - 88, (_FOOTER_H - 32) / 2,
                             88, 32, action=back_action, kind="ghost", size=12)
            cv.addSubview_(back)

    # ── Step 0: Welcome ──────────────────────────────────────────────────

    def _step_welcome(self) -> None:
        cv = self._window.contentView()

        body_top = _H - 60  # below title bar
        # Left: keycap hero
        kc_size = 128
        kc_x, kc_y = _PAD, body_top - kc_size - 40
        cv.addSubview_(keycap(kc_x, kc_y, size="xl",
                              label_text="⌥", sub="option", pressed=False))

        # Hand-drawn arrow pointing right
        cv.addSubview_(hand_arrow(kc_x + kc_size - 8, kc_y + kc_size - 24,
                                  size=60, direction="right",
                                  color=c(*ACCENT), stroke=2.2))

        # Right: text block
        tx = _PAD + kc_size + 60
        tw = _W - tx - _PAD

        # Cursive greeting
        cv.addSubview_(label("hi there —", tx, body_top - 40, tw, 30,
                             size=22, weight="hand",
                             color=c(*ACCENT), rotation=1.5))

        # Serif headline — two lines
        cv.addSubview_(label("Hold, speak,", tx, body_top - 92, tw, 40,
                             size=38, weight="serif", color=c(*INK_SOFT)))
        cv.addSubview_(label("release.", tx, body_top - 138, 180, 40,
                             size=38, weight="serif", color=c(*INK_SOFT)))
        # Hand underline under "release."
        cv.addSubview_(hand_underline(tx, body_top - 148, width=170,
                                      color=c(*ACCENT), stroke=2.4))

        # Body text
        cv.addSubview_(label(
            "Open Flow is offline voice dictation for your Mac.",
            tx, body_top - 200, tw, 20, size=14, color=c(*MUTED),
        ))
        cv.addSubview_(label(
            "Everything stays on your machine — your microphone,",
            tx, body_top - 220, tw, 20, size=14, color=c(*MUTED),
        ))
        cv.addSubview_(label(
            "your models, your words.",
            tx, body_top - 240, tw, 20, size=14, color=c(*MUTED),
        ))

        self._footer(back_action=self._finish, back_title="Skip setup",
                     primary_title="Let's go →",
                     primary_action=self._next)

    # ── Step 1: Permissions ──────────────────────────────────────────────

    def _step_permissions(self) -> None:
        cv = self._window.contentView()
        top = _H - 60

        cv.addSubview_(label("step one", _PAD, top - 30, 200, 24,
                             size=18, weight="hand", color=c(*ACCENT),
                             rotation=1.0))
        cv.addSubview_(label("Set up permissions", _PAD, top - 72, _W - _PAD * 2,
                             36, size=30, weight="serif",
                             color=c(*INK_SOFT)))
        cv.addSubview_(label(
            "Click each button, grant access in System Settings, then return here.",
            _PAD, top - 100, _W - _PAD * 2, 18, size=13, color=c(*MUTED),
        ))

        perms = [
            ("Microphone", "Record your voice while holding the hotkey.",
             "Privacy_Microphone", "🎙"),
            ("Input Monitoring", "Detect the global hotkey in any app.",
             "Privacy_ListenEvent", "⌨"),
            ("Accessibility", "Inject text into other applications.",
             "Privacy_Accessibility", "◉"),
        ]

        row_h = 68
        spacing = 10
        for i, (name, desc, pane, icon_char) in enumerate(perms):
            ry = top - 140 - i * (row_h + spacing)

            card = rect(_PAD, ry, _W - _PAD * 2, row_h,
                        color=CARD, radius=10, border=LINE)
            cv.addSubview_(card)

            # Icon badge (terracotta wash)
            icon_bg = rect(16, (row_h - 44) / 2, 44, 44,
                           color=ACCENT_W, radius=10,
                           border=(*ACCENT[:3], 0.25))
            card.addSubview_(icon_bg)
            icon_bg.addSubview_(label(icon_char, 0, 10, 44, 26,
                                      size=20, weight="medium",
                                      color=c(*ACCENT),
                                      align=NSCenterTextAlignment))

            card.addSubview_(label(name, 72, row_h - 30, 360, 20,
                                   size=14, weight="medium", color=c(*INK)))
            card.addSubview_(label(desc, 72, row_h - 50, 400, 18,
                                   size=11.5, color=c(*MUTED)))

            captured = pane
            btn = self._btn("Open Settings", 0, 0, 124, 26,
                            action=lambda p=captured: _open_privacy_pane(p),
                            kind="secondary", size=11)
            btn.setFrame_(NSMakeRect(_W - _PAD * 2 - 140, (row_h - 26) / 2,
                                     124, 26))
            card.addSubview_(btn)

        self._footer(back_action=self._back, back_title="← Back",
                     primary_title="Continue →",
                     primary_action=self._next)

    # ── Step 2: Models ───────────────────────────────────────────────────

    def _step_models(self) -> None:
        self._progress_bars = []
        self._status_labels = []
        cv = self._window.contentView()
        top = _H - 60

        cv.addSubview_(label("step two", _PAD, top - 30, 200, 24,
                             size=18, weight="hand", color=c(*ACCENT),
                             rotation=1.0))
        cv.addSubview_(label("Download models", _PAD, top - 72,
                             _W - _PAD * 2, 36,
                             size=30, weight="serif", color=c(*INK_SOFT)))
        cv.addSubview_(label(
            "Two local AI models (~3.5 GB total). Downloaded once, stored on your Mac.",
            _PAD, top - 100, _W - _PAD * 2, 18, size=13, color=c(*MUTED),
        ))

        models = [
            ("Whisper distil-large-v3", "1.5 GB · speech-to-text",
             self._cfg.whisper_model_path),
            ("Qwen2.5-3B-Instruct Q4", "2.0 GB · text cleanup",
             self._cfg.llm_model_path),
        ]

        for i, (name, size_str, path) in enumerate(models):
            ry = top - 150 - i * 104

            card = rect(_PAD, ry - 92, _W - _PAD * 2, 92,
                        color=CARD, radius=10, border=LINE)
            cv.addSubview_(card)

            card.addSubview_(label(name, 20, 62, 360, 20,
                                   size=14, weight="medium", color=c(*INK)))
            card.addSubview_(label(size_str, 20, 44, 360, 16,
                                   size=11.5, weight="mono", color=c(*MUTED)))

            bar = NSProgressIndicator.alloc().initWithFrame_(
                NSMakeRect(20, 18, _W - _PAD * 2 - 140, 8)
            )
            bar.setStyle_(1)
            bar.setIndeterminate_(False)
            bar.setMinValue_(0)
            bar.setMaxValue_(100)
            bar.setDoubleValue_(100.0 if path.exists() else 0.0)
            card.addSubview_(bar)
            self._progress_bars.append(bar)

            sl = label(
                "✓ Ready" if path.exists() else "Not downloaded",
                _W - _PAD * 2 - 120, 16, 100, 16,
                size=11.5, weight="medium",
                color=c(*(GOOD if path.exists() else SUBTLE)),
                align=NSRightTextAlignment,
            )
            card.addSubview_(sl)
            self._status_labels.append(sl)

        # Download button (left of footer buttons, inside body)
        dl_btn = self._btn("Download Models", _PAD, _FOOTER_H + 24, 160, 30,
                           action=self._start_download,
                           enabled=not self._models_ready(), size=12)
        self._download_btn = dl_btn
        cv.addSubview_(dl_btn)

        self._footer(back_action=self._back, back_title="← Back",
                     primary_title="Continue →",
                     primary_action=self._next,
                     primary_enabled=self._models_ready())

    def _models_ready(self) -> bool:
        return (
            self._cfg.whisper_model_path.exists()
            and self._cfg.llm_model_path.exists()
        )

    def _start_download(self) -> None:
        if self._download_btn:
            self._download_btn.setEnabled_(False)
        threading.Thread(target=self._download_models, daemon=True).start()

    def _download_models(self) -> None:
        from huggingface_hub import snapshot_download, hf_hub_download
        from PyObjCTools import AppHelper

        tasks = [
            ("Systran/faster-distil-whisper-large-v3",
             self._cfg.whisper_model_path, None, 0),
            ("Qwen/Qwen2.5-3B-Instruct-GGUF",
             self._cfg.llm_model_path.parent,
             "qwen2.5-3b-instruct-q4_k_m.gguf", 1),
        ]

        for repo, dest, filename, idx in tasks:
            target = dest if filename is None else dest / filename
            if target.exists():
                self._set_progress(idx, 100, "✓ Ready", GOOD)
                continue
            self._set_progress(idx, 2, "Downloading…", MUTED)
            try:
                if filename is None:
                    snapshot_download(repo_id=repo, local_dir=str(dest),
                                      local_dir_use_symlinks=False)
                else:
                    hf_hub_download(repo_id=repo, filename=filename,
                                    local_dir=str(dest))
                self._set_progress(idx, 100, "✓ Done", GOOD)
            except Exception as exc:
                self._set_progress(idx, 0, "Error", ACCENT)
                logger.error("Download failed: %s", exc)
                return

        def _enable() -> None:
            if self._next_btn:
                self._next_btn.setEnabled_(True)
        AppHelper.callAfter(_enable)

    def _set_progress(self, idx: int, value: float, status: str,
                      color_tuple) -> None:
        from PyObjCTools import AppHelper

        def _do() -> None:
            if idx < len(self._progress_bars):
                self._progress_bars[idx].setDoubleValue_(value)
            if idx < len(self._status_labels):
                self._status_labels[idx].setStringValue_(status)
                self._status_labels[idx].setTextColor_(c(*color_tuple))
        AppHelper.callAfter(_do)

    # ── Step 3: Done ─────────────────────────────────────────────────────

    def _step_done(self) -> None:
        cv = self._window.contentView()

        # Gradient checkmark icon card, centered
        icon_w = 80
        icon_x = (_W - icon_w) / 2
        icon_y = _H - 200
        icon = NSView.alloc().initWithFrame_(
            NSMakeRect(icon_x, icon_y, icon_w, icon_w)
        )
        icon.setWantsLayer_(True)

        grad = CAGradientLayer.layer()
        grad.setFrame_(NSMakeRect(0, 0, icon_w, icon_w))
        grad.setColors_([c(*ACCENT).CGColor(), c(*ACCENT_D).CGColor()])
        grad.setStartPoint_((0.0, 1.0))
        grad.setEndPoint_((1.0, 0.0))
        grad.setCornerRadius_(20)
        icon.layer().addSublayer_(grad)
        icon.layer().setCornerRadius_(20)
        icon.layer().setShadowColor_(c(*ACCENT).CGColor())
        icon.layer().setShadowOpacity_(0.3)
        icon.layer().setShadowRadius_(16)
        icon.layer().setShadowOffset_((0, -8))

        cv.addSubview_(icon)

        # Checkmark
        cv.addSubview_(label("✓", icon_x, icon_y + 16, icon_w, 46,
                             size=40, weight="bold",
                             color=c(1, 1, 1, 1),
                             align=NSCenterTextAlignment))

        # Cursive "that's it!"
        cv.addSubview_(label("that's it!", 0, icon_y - 36, _W, 30,
                             size=24, weight="hand", color=c(*ACCENT),
                             align=NSCenterTextAlignment, rotation=-1))

        # Serif "You're ready."
        cv.addSubview_(label("You're ready.", 0, icon_y - 86, _W, 44,
                             size=36, weight="serif", color=c(*INK_SOFT),
                             align=NSCenterTextAlignment))

        # Body copy
        cv.addSubview_(label(
            "Open Flow lives in your menu bar.", 0, icon_y - 126, _W, 20,
            size=14, color=c(*MUTED), align=NSCenterTextAlignment,
        ))
        cv.addSubview_(label(
            f"Hold  Right Option  in any app and start talking.",
            0, icon_y - 148, _W, 20,
            size=14, color=c(*MUTED), align=NSCenterTextAlignment,
        ))

        # Info pill (rule of thumb line)
        pill_w, pill_h = 440, 40
        pill_x = (_W - pill_w) / 2
        pill_y = icon_y - 220
        pill = rect(pill_x, pill_y, pill_w, pill_h,
                    color=CARD, radius=10, border=LINE)
        cv.addSubview_(pill)
        pill.addSubview_(label(
            "◉  menu bar, always there          ⌥  right option, hold to record",
            10, 12, pill_w - 20, 16,
            size=11, weight="mono", color=c(*MUTED),
            align=NSCenterTextAlignment,
        ))

        self._footer(back_action=self._back, back_title="← Back",
                     primary_title="Start dictating",
                     primary_action=self._finish)

    # ── Finish ───────────────────────────────────────────────────────────

    def _finish(self) -> None:
        if self._window:
            self._window.orderOut_(None)
        self._on_complete()
