"""Floating waveform HUD overlay, based on JustDictate's FloatingOverlay pattern.

States:
  recording  — animated waveform bars
  loading    — three pulsing dots
"""

from __future__ import annotations

import logging
import math

import numpy as np
import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSMakeRect,
    NSScreen,
    NSView,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskBorderless,
)

logger = logging.getLogger(__name__)

_BAR_COUNT = 24
_WIDTH = 180
_HEIGHT = 48
_BOTTOM_OFFSET = 60
_DECAY = 0.92

_WHITE = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 1.0)

# HUD display states
_STATE_RECORDING = "recording"
_STATE_LOADING = "loading"


class _WaveformView(NSView):
    def initWithFrame_(self, frame) -> "_WaveformView":
        self = objc.super(_WaveformView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._levels: list[float] = [0.05] * _BAR_COUNT
        self._state: str = _STATE_RECORDING
        self._tick: int = 0
        return self

    def setState_(self, state: str) -> None:
        self._state = state
        self.setNeedsDisplay_(True)

    def setLevels_(self, levels: list[float]) -> None:
        self._levels = levels
        self.setNeedsDisplay_(True)

    def setTick_(self, tick: int) -> None:
        self._tick = tick
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        if self._state == _STATE_LOADING:
            self._draw_loading()
        else:
            self._draw_waveform()

    def _draw_waveform(self) -> None:
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height
        n = len(self._levels)
        gap = w / n
        bar_w = max(2.0, gap * 0.6)

        for i, level in enumerate(self._levels):
            bar_h = max(2.0, level * h * 0.9)
            x = i * gap + (gap - bar_w) / 2
            y = (h - bar_h) / 2
            alpha = 0.45 + 0.55 * level
            _WHITE.colorWithAlphaComponent_(alpha).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, bar_w, bar_h), bar_w / 2, bar_w / 2
            ).fill()

    def _draw_loading(self) -> None:
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height

        dot_r = 4.0
        n_dots = 3
        spacing = 18.0
        total = (n_dots - 1) * spacing
        start_x = (w - total) / 2

        t = self._tick
        for i in range(n_dots):
            # Each dot pulses with a phase offset — creates a wave effect
            phase = (t / 8.0 - i * 0.4) * math.pi
            scale = 0.5 + 0.5 * math.sin(phase)
            r = dot_r * (0.6 + 0.4 * scale)
            alpha = 0.4 + 0.6 * scale
            cx = start_x + i * spacing
            cy = h / 2
            _WHITE.colorWithAlphaComponent_(alpha).set()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(cx - r, cy - r, r * 2, r * 2)
            ).fill()


_FADE_IN_STEP = 0.15   # alpha added per tick (~4 frames to full opacity at 30Hz)
_FADE_OUT_STEP = 0.10  # alpha removed per tick (~10 frames to invisible)


class HUD:
    def __init__(self) -> None:
        self._window: NSWindow | None = None
        self._view: _WaveformView | None = None
        self._current_rms: float = 0.0
        self._levels: list[float] = [0.05] * _BAR_COUNT
        self._state: str = _STATE_RECORDING
        self._tick: int = 0
        self._alpha: float = 0.0
        self._fading_out: bool = False

    def build(self) -> None:
        self._ensure_window()

    def show_recording(self) -> None:
        self._ensure_window()
        self._state = _STATE_RECORDING
        self._levels = [0.05] * _BAR_COUNT
        self._current_rms = 0.0
        self._fading_out = False
        if self._view:
            self._view.setState_(_STATE_RECORDING)
        if self._window:
            self._window.setAlphaValue_(0.0)
            self._window.orderFront_(None)

    def show_loading(self) -> None:
        self._ensure_window()
        self._state = _STATE_LOADING
        self._fading_out = False
        if self._view:
            self._view.setState_(_STATE_LOADING)
        if self._window and not self._window.isVisible():
            self._window.setAlphaValue_(0.0)
            self._window.orderFront_(None)

    def show(self) -> None:
        self.show_recording()

    def hide(self) -> None:
        self._fading_out = True

    def tick(self) -> None:
        if self._view is None or self._window is None:
            return
        if not self._window.isVisible():
            return

        self._tick += 1

        # Fade in / fade out
        if self._fading_out:
            self._alpha = max(0.0, self._alpha - _FADE_OUT_STEP)
            self._window.setAlphaValue_(self._alpha)
            if self._alpha <= 0.0:
                self._window.orderOut_(None)
            return
        else:
            self._alpha = min(1.0, self._alpha + _FADE_IN_STEP)
            self._window.setAlphaValue_(self._alpha)

        if self._state == _STATE_LOADING:
            self._view.setTick_(self._tick)
        else:
            rms = self._current_rms
            base = min(rms * 60, 1.0)
            phase = self._tick * 0.18
            for i in range(_BAR_COUNT):
                t = i / (_BAR_COUNT - 1)
                envelope = math.sin(math.pi * t)
                wave = 0.5 + 0.5 * math.sin(phase + t * math.pi * 2)
                target = base * envelope * (0.7 + 0.3 * wave)
                target = max(0.02, min(1.0, target))
                cur = self._levels[i]
                self._levels[i] = cur + (target - cur) * (0.25 if target > cur else 0.12)
            self._view.setLevels_(list(self._levels))

    def push_audio(self, chunk: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32768.0
        self._current_rms = max(rms, self._current_rms * 0.5)

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        screen = NSScreen.mainScreen()
        sf = screen.frame()
        x = sf.origin.x + (sf.size.width - _WIDTH) / 2
        y = sf.origin.y + _BOTTOM_OFFSET

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, _WIDTH, _HEIGHT),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        window.setLevel_(25)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        window.setIgnoresMouseEvents_(True)
        window.setCollectionBehavior_(1 << 0)

        effect = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _WIDTH, _HEIGHT)
        )
        effect.setMaterial_(2)
        effect.setState_(1)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(22)
        effect.layer().setMasksToBounds_(True)

        self._view = _WaveformView.alloc().initWithFrame_(
            NSMakeRect(14, 10, _WIDTH - 28, _HEIGHT - 20)
        )
        effect.addSubview_(self._view)
        window.contentView().addSubview_(effect)

        self._window = window
