"""Post-inject toast — small translucent pill shown for ~4s after dictation.

Clicking "Edit" expands the pill into a correction field. Submitting an
edit fires `on_correction(original, edit)`, which tray.py uses to amend
the activity log entry.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSLeftTextAlignment,
    NSMakeRect,
    NSScreen,
    NSTextField,
    NSView,
    NSVisualEffectView,
    NSVisualEffectBlendingModeBehindWindow,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject, NSTimer

from open_flow.ui.design import (
    ACCENT, ACCENT_D, CARD, GOOD, INK, INK_SOFT, LINE, MUTED, PAPER,
    SUBTLE,
    _ButtonBridge,
    c,
    label,
    make_button,
    rect,
)

logger = logging.getLogger(__name__)

_DISMISS_SECS = 4.0
_W_PILL = 460
_H_PILL = 56
_W_EDIT = 460
_H_EDIT = 96


class Toast:
    """Floating pill shown after each successful injection."""

    def __init__(self) -> None:
        self._window: NSWindow | None = None
        self._timer: NSTimer | None = None
        self._bridge: _ButtonBridge | None = None
        self._next_tag = 1
        self._current_text: str = ""
        self._current_ts: float = 0.0
        self._on_correction: Optional[Callable] = None
        self._edit_field: Optional[NSTextField] = None

    # ── Public ───────────────────────────────────────────────────────────

    def show(self, text: str, latency: float, app: str,
             timestamp: float,
             on_correction: Optional[Callable[[str, str], None]] = None) -> None:
        self._current_text = text
        self._current_ts = timestamp
        self._on_correction = on_correction
        self._ensure_window()
        self._build_pill(text, latency, app)
        self._position_window(_W_PILL, _H_PILL)
        self._window.orderFrontRegardless()
        self._reset_timer()

    def hide(self) -> None:
        self._cancel_timer()
        if self._window:
            self._window.orderOut_(None)

    # ── Window ───────────────────────────────────────────────────────────

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, _W_PILL, _H_PILL),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setReleasedWhenClosed_(False)
        self._window.setHasShadow_(True)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorStationary |
            NSWindowCollectionBehaviorIgnoresCycle
        )
        self._bridge = _ButtonBridge.alloc().initWithMap_({})

    def _position_window(self, w: float, h: float) -> None:
        screen = NSScreen.mainScreen()
        sf = screen.visibleFrame()
        x = sf.origin.x + (sf.size.width - w) / 2
        y = sf.origin.y + 48
        self._window.setFrame_display_(NSMakeRect(x, y, w, h), True)

    def _clear(self) -> None:
        for sub in list(self._window.contentView().subviews()):
            sub.removeFromSuperview()
        self._bridge._map.clear()
        self._next_tag = 1

    def _btn(self, title: str, x: float, y: float, w: float, h: float,
             action: Callable, kind: str = "secondary",
             size: float = 11) -> NSButton:
        tag = self._next_tag
        self._next_tag += 1
        return make_button(title, x, y, w, h, kind=kind,
                           bridge=self._bridge, tag=tag, action=action,
                           size=size)

    # ── Pill view ────────────────────────────────────────────────────────

    def _build_pill(self, text: str, latency: float, app: str) -> None:
        self._clear()
        cv = self._window.contentView()

        # Blur background — NSVisualEffectView filling the full pill,
        # corner-rounded so the whole window looks like a translucent pill.
        blur = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _W_PILL, _H_PILL)
        )
        blur.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        try:
            blur.setMaterial_(7)   # NSVisualEffectMaterialWindowBackground
        except Exception:
            pass
        blur.setState_(1)
        blur.setWantsLayer_(True)
        blur.layer().setCornerRadius_(_H_PILL / 2)
        blur.layer().setMasksToBounds_(True)
        blur.layer().setBorderWidth_(0.5)
        blur.layer().setBorderColor_(c(*LINE).CGColor())
        cv.addSubview_(blur)

        # Warm paper tint overlay on top of the blur so the pill has a
        # subtle paper look (otherwise NSVisualEffectMaterialWindowBackground
        # is a cool gray).
        tint = rect(0, 0, _W_PILL, _H_PILL,
                    color=(*PAPER[:3], 0.45), radius=_H_PILL / 2)
        blur.addSubview_(tint)

        # Green status dot
        tint.addSubview_(rect(18, _H_PILL / 2 - 4, 8, 8,
                              color=GOOD, radius=4))

        # Transcript text (truncated)
        preview = text[:64] + ("…" if len(text) > 64 else "")
        tint.addSubview_(label(f'"{preview}"', 34, _H_PILL - 30,
                               _W_PILL - 180, 18,
                               size=12.5, weight="medium",
                               color=c(*INK_SOFT)))

        # Meta line
        tint.addSubview_(label(f"→ {app} · {latency:.2f}s",
                               34, 8, 220, 14,
                               size=10.5, weight="mono", color=c(*MUTED)))

        # Edit button
        tint.addSubview_(self._btn("Edit",
                                   _W_PILL - 120, (_H_PILL - 26) / 2,
                                   52, 26,
                                   action=self._open_edit,
                                   kind="secondary", size=11))
        # Dismiss
        tint.addSubview_(self._btn("✕",
                                   _W_PILL - 56, (_H_PILL - 26) / 2,
                                   32, 26,
                                   action=self.hide,
                                   kind="ghost", size=12))

    # ── Edit view ────────────────────────────────────────────────────────

    def _open_edit(self) -> None:
        self._cancel_timer()
        self._clear()
        self._position_window(_W_EDIT, _H_EDIT)

        cv = self._window.contentView()

        blur = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _W_EDIT, _H_EDIT)
        )
        blur.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        try:
            blur.setMaterial_(7)
        except Exception:
            pass
        blur.setState_(1)
        blur.setWantsLayer_(True)
        blur.layer().setCornerRadius_(16)
        blur.layer().setMasksToBounds_(True)
        blur.layer().setBorderWidth_(0.5)
        blur.layer().setBorderColor_(c(*LINE).CGColor())
        cv.addSubview_(blur)

        tint = rect(0, 0, _W_EDIT, _H_EDIT,
                    color=(*PAPER[:3], 0.45), radius=16)
        blur.addSubview_(tint)

        tint.addSubview_(label("Edit — teach Open Flow your style:",
                               16, _H_EDIT - 24, _W_EDIT - 32, 14,
                               size=10.5, weight="medium", color=c(*MUTED),
                               kern=0.3))

        field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, 38, _W_EDIT - 32, 28)
        )
        field.setStringValue_(self._current_text)
        field.setEditable_(True)
        field.setSelectable_(True)
        field.setBezeled_(True)
        field.setBezelStyle_(0)
        field.setDrawsBackground_(True)
        field.setFont_(NSFont.systemFontOfSize_(13))
        field.setTextColor_(c(*INK))
        tint.addSubview_(field)
        self._edit_field = field

        # Save + cancel buttons (in the row below)
        tint.addSubview_(self._btn("Cancel", 16, 8, 80, 24,
                                   action=self.hide, kind="ghost", size=11))
        tint.addSubview_(self._btn("Save correction",
                                   _W_EDIT - 16 - 140, 8, 140, 24,
                                   action=self._save_correction,
                                   kind="primary", size=11))

        self._window.makeFirstResponder_(field)

    def _save_correction(self) -> None:
        edit = ""
        if self._edit_field is not None:
            edit = self._edit_field.stringValue().strip()
        if edit and edit != self._current_text and self._on_correction:
            self._on_correction(self._current_text, edit)
        self.hide()

    # ── Timer ────────────────────────────────────────────────────────────

    def _reset_timer(self) -> None:
        self._cancel_timer()
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            _DISMISS_SECS, self._window, "orderOut:", None, False,
        )

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.invalidate()
            self._timer = None
