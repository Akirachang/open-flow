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
from Quartz import (
    CATransaction,
    CATransform3DConcat,
    CATransform3DMakeScale,
    CATransform3DMakeTranslation,
)

logger = logging.getLogger(__name__)

_BAR_COUNT = 18
_WIDTH = 120
_HEIGHT = 36
_CORNER_RADIUS = _HEIGHT / 2  # full pill, like Wispr Flow
_PAD = 14  # transparent margin around the pill so the spring overshoot doesn't clip
_WINDOW_W = _WIDTH + 2 * _PAD
_WINDOW_H = _HEIGHT + 2 * _PAD
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
        # Wispr-style: a row of small dots/short bars centered vertically.
        # At rest they read as a horizontal line of dots; speaking grows them.
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height
        n = len(self._levels)
        gap = w / n
        bar_w = max(1.5, gap * 0.42)
        min_h = 1.5  # idle dot height
        max_h = h * 0.55  # peak bar height — never fills the pill

        for i, level in enumerate(self._levels):
            bar_h = min_h + level * (max_h - min_h)
            x = i * gap + (gap - bar_w) / 2
            y = (h - bar_h) / 2
            alpha = 0.55 + 0.45 * level
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


_FADE_IN_STEP = 0.55   # alpha added per tick (~2 frames to full opacity at 30Hz)
_APPEAR_FRAMES = 7     # spring-pop duration after show (~230ms)
_APPEAR_START_SCALE = 0.55  # initial pop scale before easing up to 1.0
_DISAPPEAR_FRAMES = 3  # shrink-and-vanish duration on hide (~100ms)
_DISAPPEAR_END_SCALE = 0.55  # scale at the moment of vanishing


def _ease_out_back(p: float) -> float:
    """easeOutBack — overshoots above 1.0 then settles, gives a 'snap' feel."""
    p = max(0.0, min(1.0, p))
    c1 = 1.70158
    c3 = c1 + 1
    p1 = p - 1
    return 1 + c3 * p1 * p1 * p1 + c1 * p1 * p1


def _ease_in_quint(p: float) -> float:
    """easeInQuint — strong hold-then-snap, no anticipation/overshoot."""
    p = max(0.0, min(1.0, p))
    return p * p * p * p * p


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
        self._appear_tick: int = _APPEAR_FRAMES  # _APPEAR_FRAMES = "settled at 1.0"
        self._disappear_tick: int = 0

    def build(self) -> None:
        self._ensure_window()

    def show_recording(self) -> None:
        self._ensure_window()
        self._state = _STATE_RECORDING
        self._levels = [0.05] * _BAR_COUNT
        self._current_rms = 0.0
        self._fading_out = False
        self._appear_tick = 0
        if self._view:
            self._view.setState_(_STATE_RECORDING)
        if self._window:
            self._window.setAlphaValue_(0.0)
            self._apply_pop_scale(_APPEAR_START_SCALE)
            self._window.orderFront_(None)

    def show_loading(self) -> None:
        self._ensure_window()
        self._state = _STATE_LOADING
        self._fading_out = False
        if self._view:
            self._view.setState_(_STATE_LOADING)
        if self._window and not self._window.isVisible():
            self._appear_tick = 0
            self._window.setAlphaValue_(0.0)
            self._apply_pop_scale(_APPEAR_START_SCALE)
            self._window.orderFront_(None)

    def show(self) -> None:
        self.show_recording()

    def hide(self) -> None:
        if not self._fading_out:
            self._disappear_tick = 0
        self._fading_out = True

    def tick(self) -> None:
        if self._view is None or self._window is None:
            return
        if not self._window.isVisible():
            return

        self._tick += 1

        # Fade in / fade out
        if self._fading_out:
            self._disappear_tick = min(self._disappear_tick + 1, _DISAPPEAR_FRAMES)
            p = self._disappear_tick / _DISAPPEAR_FRAMES
            eased = _ease_in_quint(p)
            self._alpha = max(0.0, 1.0 - eased)
            scale = 1.0 + (_DISAPPEAR_END_SCALE - 1.0) * eased
            self._window.setAlphaValue_(self._alpha)
            self._apply_pop_scale(scale)
            if self._disappear_tick >= _DISAPPEAR_FRAMES:
                self._window.orderOut_(None)
                self._apply_pop_scale(1.0)  # reset for next show
            return
        else:
            self._alpha = min(1.0, self._alpha + _FADE_IN_STEP)
            self._window.setAlphaValue_(self._alpha)

        # Spring-pop scale during the appear phase
        if self._appear_tick < _APPEAR_FRAMES:
            self._appear_tick += 1
            p = self._appear_tick / _APPEAR_FRAMES
            eased = _ease_out_back(p)
            scale = _APPEAR_START_SCALE + (1.0 - _APPEAR_START_SCALE) * eased
            self._apply_pop_scale(scale)
            if self._appear_tick >= _APPEAR_FRAMES:
                self._apply_pop_scale(1.0)

        if self._state == _STATE_LOADING:
            self._view.setTick_(self._tick)
        else:
            rms = self._current_rms
            base = min(rms * 220, 1.0)
            phase = self._tick * 0.18
            for i in range(_BAR_COUNT):
                t = i / (_BAR_COUNT - 1)
                envelope = math.sin(math.pi * t)
                wave = 0.5 + 0.5 * math.sin(phase + t * math.pi * 2)
                target = base * envelope * (0.7 + 0.3 * wave)
                target = max(0.02, min(1.0, target))
                cur = self._levels[i]
                self._levels[i] = cur + (target - cur) * (0.75 if target > cur else 0.35)
            self._view.setLevels_(list(self._levels))

    def _apply_pop_scale(self, scale: float) -> None:
        if self._window is None:
            return
        layer = self._window.contentView().layer()
        if layer is None:
            return
        cx, cy = _WINDOW_W / 2, _WINDOW_H / 2
        t = CATransform3DConcat(
            CATransform3DConcat(
                CATransform3DMakeTranslation(-cx, -cy, 0),
                CATransform3DMakeScale(scale, scale, 1.0),
            ),
            CATransform3DMakeTranslation(cx, cy, 0),
        )
        # Disable the implicit layer animation — we drive the easing ourselves.
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        layer.setSublayerTransform_(t)
        CATransaction.commit()

    def push_audio(self, chunk: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32768.0
        self._current_rms = max(rms, self._current_rms * 0.12)

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        screen = NSScreen.mainScreen()
        sf = screen.frame()
        # Window is _PAD bigger on every side than the visible pill so the
        # spring-pop overshoot has room without hitting the window clip.
        x = sf.origin.x + (sf.size.width - _WINDOW_W) / 2
        y = sf.origin.y + _BOTTOM_OFFSET - _PAD

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, _WINDOW_W, _WINDOW_H),
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
        # Layer-back the contentView so we can drive a sublayerTransform
        # for the spring-pop appear animation.
        window.contentView().setWantsLayer_(True)

        effect = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(_PAD, _PAD, _WIDTH, _HEIGHT)
        )
        # Material 8 = HUD window — darker base than material 2.
        effect.setMaterial_(8)
        effect.setState_(1)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(_CORNER_RADIUS)
        effect.layer().setMasksToBounds_(True)

        # Dark overlay on top of the blur for the solid near-black look.
        # Drops translucency without losing all of the depth from the blur.
        darken = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _WIDTH, _HEIGHT)
        )
        darken.setWantsLayer_(True)
        darken.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.02, 0.02, 0.03, 0.94
            ).CGColor()
        )
        effect.addSubview_(darken)

        self._view = _WaveformView.alloc().initWithFrame_(
            NSMakeRect(20, 6, _WIDTH - 40, _HEIGHT - 12)
        )
        effect.addSubview_(self._view)
        window.contentView().addSubview_(effect)

        self._window = window
