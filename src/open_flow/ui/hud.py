"""Floating waveform HUD overlay, based on JustDictate's FloatingOverlay pattern.

States:
  recording  — animated waveform bars
  loading    — bars stay visible (idling at silence) and the pill grows on
               the right to reveal a spinning wheel
"""

from __future__ import annotations

import logging
import math
import random

import numpy as np
import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSMakePoint,
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

_BAR_COUNT = 14
_WIDTH = 100
_HEIGHT = 30
_CORNER_RADIUS = _HEIGHT / 2  # full pill, like Wispr Flow
_PAD = 14  # transparent margin around the pill so the spring overshoot doesn't clip
_SPINNER_SIZE = 14   # spinner-view side length
_SPINNER_GAP = 8     # gap between the bars' right edge and the spinner
_SPINNER_RIGHT_PAD = 12  # gap between the spinner's right edge and the pill border
# Pill grows on the right just enough to fit: gap + spinner + right padding,
# minus the spare right padding that was already there in the recording state.
_RECORDING_RIGHT_PAD = 20  # bars are inset 20 from each side of the recording pill
_LOADING_EXTRA = _SPINNER_GAP + _SPINNER_SIZE + _SPINNER_RIGHT_PAD - _RECORDING_RIGHT_PAD
_GROW_RATE = 0.55    # per-tick lerp toward the target pill width
_WINDOW_W = _WIDTH + _LOADING_EXTRA + 2 * _PAD  # max width — sized for the loading state
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
        return self

    def setLevels_(self, levels: list[float]) -> None:
        self._levels = levels
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        # Wispr-style: a row of small dots/short bars centered vertically.
        # At rest they read as a horizontal line of dots; speaking grows them.
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height
        n = len(self._levels)
        gap = w / n
        bar_w = max(1.5, gap * 0.42)
        min_h = 1.5  # idle dot height
        max_h = h * 0.48  # peak bar height — never fills the pill

        for i, level in enumerate(self._levels):
            bar_h = min_h + level * (max_h - min_h)
            x = i * gap + (gap - bar_w) / 2
            y = (h - bar_h) / 2
            alpha = 0.55 + 0.45 * level
            _WHITE.colorWithAlphaComponent_(alpha).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, bar_w, bar_h), bar_w / 2, bar_w / 2
            ).fill()


class _SpinnerView(NSView):
    """Eight rotating spokes with a fading-tail alpha pattern."""

    _N_SPOKES = 8
    _TICKS_PER_REV = 24  # ~0.8s per revolution at 30Hz

    def initWithFrame_(self, frame) -> "_SpinnerView":
        self = objc.super(_SpinnerView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._tick: int = 0
        return self

    def setTick_(self, tick: int) -> None:
        self._tick = tick
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        bounds = self.bounds()
        cx = bounds.size.width / 2.0
        cy = bounds.size.height / 2.0
        outer_r = min(cx, cy) - 1.5
        inner_r = outer_r * 0.5
        phase = (self._tick / self._TICKS_PER_REV) * 2.0 * math.pi
        for i in range(self._N_SPOKES):
            angle = phase + i * 2.0 * math.pi / self._N_SPOKES
            # Trailing-fade alpha: brightest spoke is the leading one,
            # alpha decreases around the wheel.
            alpha = 0.18 + 0.82 * ((i + 1) / self._N_SPOKES)
            x1 = cx + math.cos(angle) * inner_r
            y1 = cy + math.sin(angle) * inner_r
            x2 = cx + math.cos(angle) * outer_r
            y2 = cy + math.sin(angle) * outer_r
            path = NSBezierPath.bezierPath()
            path.setLineWidth_(1.6)
            path.setLineCapStyle_(1)  # NSLineCapStyleRound
            path.moveToPoint_(NSMakePoint(x1, y1))
            path.lineToPoint_(NSMakePoint(x2, y2))
            _WHITE.colorWithAlphaComponent_(alpha).set()
            path.stroke()


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
        self._effect: NSVisualEffectView | None = None
        self._darken: NSView | None = None
        self._spinner: _SpinnerView | None = None
        self._current_rms: float = 0.0
        self._levels: list[float] = [0.05] * _BAR_COUNT
        self._state: str = _STATE_RECORDING
        self._tick: int = 0
        self._alpha: float = 0.0
        self._fading_out: bool = False
        # _dismissing covers the "shrink the wheel area first" phase that runs
        # before the snap-shrink-and-vanish phase (_fading_out).
        self._dismissing: bool = False
        self._appear_tick: int = _APPEAR_FRAMES  # _APPEAR_FRAMES = "settled at 1.0"
        self._disappear_tick: int = 0
        # Smoothly-eased extra width on the right of the pill for the spinner.
        self._extra_width: float = 0.0
        self._target_extra_width: float = 0.0

    def build(self) -> None:
        self._ensure_window()

    def show_recording(self) -> None:
        self._ensure_window()
        self._state = _STATE_RECORDING
        self._levels = [0.05] * _BAR_COUNT
        self._current_rms = 0.0
        self._fading_out = False
        self._dismissing = False
        self._appear_tick = 0
        # Snap pill back to the narrow recording size before the pop animation.
        self._extra_width = 0.0
        self._target_extra_width = 0.0
        self._apply_extra_width(0.0)
        if self._window:
            self._window.setAlphaValue_(0.0)
            self._apply_pop_scale(_APPEAR_START_SCALE)
            self._window.orderFront_(None)

    def show_loading(self) -> None:
        self._ensure_window()
        was_visible = self._window is not None and self._window.isVisible()
        self._state = _STATE_LOADING
        self._fading_out = False
        self._dismissing = False
        # Drive the pill to grow on the right; tick() will lerp it open.
        self._target_extra_width = float(_LOADING_EXTRA)
        if self._window and not was_visible:
            # First-time show (unusual: loading without a prior recording) —
            # start from the narrow size and pop in like recording.
            self._extra_width = 0.0
            self._apply_extra_width(0.0)
            self._appear_tick = 0
            self._window.setAlphaValue_(0.0)
            self._apply_pop_scale(_APPEAR_START_SCALE)
            self._window.orderFront_(None)

    def show(self) -> None:
        self.show_recording()

    def hide(self) -> None:
        if self._fading_out or self._dismissing:
            return  # already on the way out
        # If the pill is wider than recording size, first close the wheel
        # area; tick() will start the snap-shrink-and-vanish once it reaches
        # the recording width.
        self._target_extra_width = 0.0
        if self._extra_width > 0.5:
            self._dismissing = True
        else:
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

        # Smooth growth/shrink of the pill toward its target width.
        if abs(self._extra_width - self._target_extra_width) > 0.5:
            self._extra_width += (
                self._target_extra_width - self._extra_width
            ) * _GROW_RATE
            self._apply_extra_width(self._extra_width)
        elif self._extra_width != self._target_extra_width:
            self._extra_width = self._target_extra_width
            self._apply_extra_width(self._extra_width)

        # If we were closing the wheel area as a prelude to dismissing,
        # hand off to the snap-shrink-and-vanish phase now that the pill is
        # back at recording width.
        if self._dismissing and self._extra_width <= 0.5:
            self._extra_width = 0.0
            self._apply_extra_width(0.0)
            self._dismissing = False
            self._disappear_tick = 0
            self._fading_out = True

        # Drive the spinner once it's at all visible.
        if self._spinner is not None and self._extra_width > 0.5:
            self._spinner.setTick_(self._tick)

        if self._state == _STATE_LOADING:
            # Loading: freeze the wave. Decay any in-flight levels down to
            # idle dots quickly, then stop pumping the view.
            settled = True
            for i in range(_BAR_COUNT):
                if self._levels[i] > 0.025:
                    self._levels[i] += (0.0 - self._levels[i]) * 0.5
                    settled = False
            if not settled:
                self._view.setLevels_(list(self._levels))
        else:
            # Recording: bars track the mic with a noise-floor gate so
            # background hum doesn't keep them twitching when silent.
            rms = self._current_rms
            if rms < 0.008:
                base = 0.0
            else:
                base = min((rms - 0.008) * 220, 1.0)
            for i in range(_BAR_COUNT):
                t = i / (_BAR_COUNT - 1)
                envelope = 0.55 + 0.45 * math.sin(math.pi * t)
                jitter = random.uniform(0.65, 1.15)
                target = base * envelope * jitter
                target = max(0.02, min(1.0, target))
                cur = self._levels[i]
                self._levels[i] = cur + (target - cur) * (
                    0.55 if target > cur else 0.32
                )
            self._view.setLevels_(list(self._levels))

    def _apply_pop_scale(self, scale: float) -> None:
        if self._window is None:
            return
        layer = self._window.contentView().layer()
        if layer is None:
            return
        # Scale around the visible pill's center, not the window center —
        # the pill is left-anchored inside an oversized window so the
        # right side has room to grow during loading.
        pill_w = _WIDTH + self._extra_width
        cx = _PAD + pill_w / 2
        cy = _PAD + _HEIGHT / 2
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

    def _apply_extra_width(self, extra: float) -> None:
        """Resize the visible pill (effect view + dark overlay) on the right."""
        if self._effect is None or self._darken is None:
            return
        pill_w = _WIDTH + extra
        self._effect.setFrame_(NSMakeRect(_PAD, _PAD, pill_w, _HEIGHT))
        self._darken.setFrame_(NSMakeRect(0, 0, pill_w, _HEIGHT))
        if self._spinner is not None:
            # Fade the spinner in proportional to how far the pill has grown,
            # so it doesn't pop in fully-formed when the rounded corner reaches it.
            fade = max(0.0, min(1.0, extra / _LOADING_EXTRA))
            self._spinner.setAlphaValue_(fade)
        if self._window is not None:
            self._window.invalidateShadow()

    def push_audio(self, chunk: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32768.0
        self._current_rms = max(rms, self._current_rms * 0.12)

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        screen = NSScreen.mainScreen()
        sf = screen.frame()
        # The window is sized for the loading-state max width so the pill can
        # grow on the right without resizing the window. Position it so that
        # the recording-state pill (left-anchored with _PAD margin) is centered
        # on screen.
        x = sf.origin.x + (sf.size.width - _WIDTH) / 2 - _PAD
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

        # Spinner sits a few px to the right of the bars at a fixed position.
        # During recording it's hidden by alpha=0; as the pill grows it
        # fades in and the new pill area provides breathing room on its right.
        bars_right_edge = 20 + (_WIDTH - 40)  # see _view's frame above
        spinner_x = bars_right_edge + _SPINNER_GAP
        spinner_y = (_HEIGHT - _SPINNER_SIZE) / 2
        spinner = _SpinnerView.alloc().initWithFrame_(
            NSMakeRect(spinner_x, spinner_y, _SPINNER_SIZE, _SPINNER_SIZE)
        )
        spinner.setAlphaValue_(0.0)
        effect.addSubview_(spinner)

        window.contentView().addSubview_(effect)

        self._window = window
        self._effect = effect
        self._darken = darken
        self._spinner = spinner
