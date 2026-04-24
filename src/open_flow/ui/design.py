"""Shared design primitives — paper-grain Claude aesthetic.

This module centralizes the color tokens, font loaders, and drawing
primitives (hand-drawn SVG accents, paper grain, custom buttons,
gradient cards) that every UI module needs.

Why it exists:
- Before this, onboarding/dashboard/toast each redefined `_c`, `_label`,
  `_rect`, and the entire palette. That duplication made every drift a
  three-place edit.
- Custom chrome (buttons, toggles, gradient layers) needs shared NSObject
  delegate classes; defining them once avoids PyObjC selector collisions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Sequence

import objc
from AppKit import (
    NSAttributedString,
    NSBezierPath,
    NSBezelStyleRounded,
    NSButton,
    NSButtonCell,
    NSCenterTextAlignment,
    NSColor,
    NSFont,
    NSFontDescriptor,
    NSFontManager,
    NSFontDescriptorSymbolicTraits,
    NSGradient,
    NSImage,
    NSImageView,
    NSLeftTextAlignment,
    NSMakeRect,
    NSMakePoint,
    NSMakeSize,
    NSMomentaryLightButton,
    NSParagraphStyle,
    NSMutableParagraphStyle,
    NSRightTextAlignment,
    NSStrikethroughStyleAttributeName,
    NSStrikethroughColorAttributeName,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSParagraphStyleAttributeName,
    NSKernAttributeName,
    NSTextAlignmentCenter,
    NSTextField,
    NSView,
    NSVisualEffectView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectBlendingModeWithinWindow,
)
from Foundation import NSObject
from Quartz import (
    CAGradientLayer,
    CALayer,
    CAShapeLayer,
    CGColorCreateGenericRGB,
    CGPathCreateMutable,
    CGPathMoveToPoint,
    CGPathAddCurveToPoint,
    CGPathAddLineToPoint,
)

logger = logging.getLogger(__name__)

# ── Design tokens ──────────────────────────────────────────────────────────

PAPER    = (0.961, 0.945, 0.922, 1.0)   # #F5F1EB
PAPER_D  = (0.929, 0.906, 0.859, 1.0)   # #EDE7DB
CARD     = (0.980, 0.969, 0.945, 1.0)   # #FAF7F1
INK      = (0.122, 0.106, 0.086, 1.0)   # #1F1B16
INK_SOFT = (0.235, 0.200, 0.161, 1.0)   # #3C332A
MUTED    = (0.420, 0.373, 0.322, 1.0)   # #6B5F52
SUBTLE   = (0.573, 0.518, 0.467, 1.0)   # #928477
ACCENT   = (0.788, 0.392, 0.259, 1.0)   # #C96442
ACCENT_D = (0.659, 0.286, 0.180, 1.0)   # #A8492E
ACCENT_W = (0.949, 0.839, 0.780, 1.0)   # #F2D6C7
ACCENT_I = (0.431, 0.169, 0.090, 1.0)   # #6E2B17
GOOD     = (0.369, 0.541, 0.306, 1.0)   # #5E8A4E
WARN     = (0.769, 0.541, 0.169, 1.0)
DANGER   = (0.714, 0.314, 0.235, 1.0)   # #B6503C
LINE     = (0.235, 0.200, 0.161, 0.12)
LINE_STR = (0.235, 0.200, 0.161, 0.22)
LINE_H   = (0.235, 0.200, 0.161, 0.07)


def c(*rgba) -> NSColor:
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgba)


# ── Font resolution ────────────────────────────────────────────────────────
# We try Caveat first (if installed system-wide), then fall back to
# Bradley Hand / Snell Roundhand / Georgia italic so the cursive feel is
# at least approximated on stock macOS.

_HAND_CANDIDATES = [
    "Caveat",
    "Caveat-Regular",
    "Patrick Hand",
    "Bradley Hand",
    "Snell Roundhand",
    "Georgia-Italic",
]

_SERIF_CANDIDATES = [
    "Source Serif 4",
    "SourceSerif4-Regular",
    "Source Serif Pro",
    "Charter",
    "Iowan Old Style",
    "Georgia",
]


def _resolve_font(candidates: Sequence[str], size: float,
                  fallback) -> NSFont:
    for name in candidates:
        font = NSFont.fontWithName_size_(name, size)
        if font is not None:
            return font
    return fallback


def font_hand(size: float) -> NSFont:
    """Cursive / hand-drawn font — Caveat if available, else italic fallback."""
    italic_desc = NSFont.systemFontOfSize_(size).fontDescriptor().fontDescriptorWithSymbolicTraits_(
        1 << 0  # NSFontDescriptorTraitItalic
    )
    italic = NSFont.fontWithDescriptor_size_(italic_desc, size) or NSFont.systemFontOfSize_(size)
    return _resolve_font(_HAND_CANDIDATES, size, italic)


def font_serif(size: float, weight: float = 0.0) -> NSFont:
    """Editorial serif for headlines."""
    fallback = NSFont.systemFontOfSize_(size)
    return _resolve_font(_SERIF_CANDIDATES, size, fallback)


def font_sans(size: float, weight: float = 0.0) -> NSFont:
    return NSFont.systemFontOfSize_weight_(size, weight)


def font_mono(size: float) -> NSFont:
    return NSFont.monospacedSystemFontOfSize_weight_(size, 0.0)


# ── Label helper ───────────────────────────────────────────────────────────

def label(text: str, x: float, y: float, w: float, h: float,
          size: float = 13, weight: str = "regular",
          color=None, align: int = NSLeftTextAlignment,
          rotation: float = 0.0,
          strikethrough: bool = False,
          kern: float = 0.0) -> NSTextField:
    """Unified label factory. `weight` is one of:
    regular / medium / bold / serif / serif-medium / hand / mono.
    Strikethrough is rendered via NSAttributedString.
    """
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setAlignment_(align)

    if weight == "bold":
        font = NSFont.boldSystemFontOfSize_(size)
    elif weight == "medium":
        font = font_sans(size, 0.23)
    elif weight == "serif":
        font = font_serif(size)
    elif weight == "serif-medium":
        font = font_serif(size, 0.23)
    elif weight == "hand":
        font = font_hand(size)
    elif weight == "mono":
        font = font_mono(size)
    else:
        font = font_sans(size)

    text_color = color or c(*INK)

    if strikethrough or kern:
        attrs = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: text_color,
        }
        if strikethrough:
            attrs[NSStrikethroughStyleAttributeName] = 1
            attrs[NSStrikethroughColorAttributeName] = c(*ACCENT_D, a=0.4) if False else text_color
        if kern:
            attrs[NSKernAttributeName] = kern
        para = NSMutableParagraphStyle.alloc().init()
        if align == NSCenterTextAlignment:
            para.setAlignment_(NSTextAlignmentCenter)
        elif align == NSRightTextAlignment:
            para.setAlignment_(2)  # right
        attrs[NSParagraphStyleAttributeName] = para
        attr_str = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        f.setAttributedStringValue_(attr_str)
    else:
        f.setStringValue_(text)
        f.setFont_(font)
        f.setTextColor_(text_color)

    f.setLineBreakMode_(0)

    if rotation:
        f.setWantsLayer_(True)
        import math
        f.setFrameCenterRotation_(rotation)

    return f


# ── Rect / card view ───────────────────────────────────────────────────────

def rect(x: float, y: float, w: float, h: float,
         color=None, radius: float = 0,
         border=None, border_width: float = 0.5) -> NSView:
    v = NSView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    v.setWantsLayer_(True)
    layer = v.layer()
    if color:
        layer.setBackgroundColor_(c(*color).CGColor())
    if radius:
        layer.setCornerRadius_(radius)
    if border:
        layer.setBorderWidth_(border_width)
        layer.setBorderColor_(c(*border).CGColor())
    return v


def gradient_rect(x: float, y: float, w: float, h: float,
                  top_color, bottom_color,
                  radius: float = 0, angle: float = 135.0) -> NSView:
    """Diagonal gradient card. `angle` is in degrees (135 = top-left to bottom-right)."""
    v = NSView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    v.setWantsLayer_(True)
    grad = CAGradientLayer.layer()
    grad.setFrame_(NSMakeRect(0, 0, w, h))
    grad.setColors_([c(*top_color).CGColor(), c(*bottom_color).CGColor()])
    # Convert angle to start/end points
    import math
    rad = math.radians(angle)
    grad.setStartPoint_((0.0, 0.0))
    grad.setEndPoint_((math.cos(rad), math.sin(rad)))
    if radius:
        grad.setCornerRadius_(radius)
    v.layer().addSublayer_(grad)
    if radius:
        v.layer().setCornerRadius_(radius)
        v.layer().setMasksToBounds_(True)
    return v


# ── Paper grain overlay ────────────────────────────────────────────────────
# Generated once as a 200×200 tile and reused via CALayer contents.

_grain_image: Optional[NSImage] = None


def _make_grain_image(size: int = 200) -> NSImage:
    """Generate a subtle warm-multiply noise tile, as a cached NSImage."""
    import random
    from AppKit import NSBitmapImageRep, NSCalibratedRGBColorSpace

    random.seed(42)  # deterministic grain
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False,
        NSCalibratedRGBColorSpace, 0, 0,
    )
    for yy in range(size):
        for xx in range(size):
            n = random.random()
            # Warm brown tint, low alpha
            r = 0.12 * n
            g = 0.10 * n
            b = 0.08 * n
            a = 0.055 * n
            rep.setColor_atX_y_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a),
                xx, yy,
            )
    img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.addRepresentation_(rep)
    return img


def grain_image() -> NSImage:
    global _grain_image
    if _grain_image is None:
        _grain_image = _make_grain_image()
    return _grain_image


def apply_grain(view: NSView) -> None:
    """Overlay a tiled grain layer on the view."""
    try:
        img = grain_image()
        layer = CALayer.layer()
        layer.setFrame_(view.bounds())
        layer.setContents_(img)
        layer.setContentsGravity_("resize")  # tile approximation
        layer.setOpacity_(0.35)
        layer.setCompositingFilter_(None)
        view.setWantsLayer_(True)
        view.layer().addSublayer_(layer)
    except Exception as exc:
        logger.debug("Grain overlay skipped: %s", exc)


# ── Hand-drawn SVG accents ─────────────────────────────────────────────────
# Rendered via NSBezierPath on a transparent NSView. Paths are approximations
# of the SVG curves from the design reference.

class _ShapeView(NSView):
    """Simple NSView that draws a user-supplied NSBezierPath on each draw."""

    def initWithFrame_path_color_stroke_(self, frame, path, color, stroke):
        self = objc.super(_ShapeView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._path = path
        self._color = color
        self._stroke = stroke
        return self

    def drawRect_(self, dirty):
        self._color.set()
        self._path.setLineWidth_(self._stroke)
        self._path.setLineCapStyle_(1)  # round
        self._path.setLineJoinStyle_(1)  # round
        self._path.stroke()


def hand_underline(x: float, y: float, width: float = 170,
                   color=None, stroke: float = 2.4) -> NSView:
    """Sketchy single-stroke underline — matches CL HandUnderline."""
    color = color or c(*ACCENT)
    height = 12
    path = NSBezierPath.bezierPath()
    # Scaled version of: M2 7 C 18 3, 38 9, 58 5 S 98 8, 118 4 S 150 9, 158 6
    scale = width / 160
    path.moveToPoint_((2 * scale, 5))
    path.curveToPoint_controlPoint1_controlPoint2_(
        (58 * scale, 7), (18 * scale, 9), (38 * scale, 3),
    )
    path.curveToPoint_controlPoint1_controlPoint2_(
        (118 * scale, 8), (78 * scale, 1), (98 * scale, 4),
    )
    path.curveToPoint_controlPoint1_controlPoint2_(
        (158 * scale, 6), (138 * scale, 0), (150 * scale, 3),
    )
    v = _ShapeView.alloc().initWithFrame_path_color_stroke_(
        NSMakeRect(x, y, width, height), path, color, stroke,
    )
    return v


def hand_arrow(x: float, y: float, size: float = 56,
               direction: str = "right", color=None,
               stroke: float = 2.0) -> NSView:
    """Inky curved arrow with arrowhead. direction: right / down / downRight."""
    color = color or c(*MUTED)
    scale = size / 60

    path = NSBezierPath.bezierPath()
    if direction == "right":
        path.moveToPoint_((6 * scale, size - 28 * scale))
        path.curveToPoint_controlPoint1_controlPoint2_(
            (48 * scale, size - 20 * scale),
            (16 * scale, size - 14 * scale),
            (32 * scale, size - 14 * scale),
        )
        # Arrowhead
        path.moveToPoint_((48 * scale, size - 14 * scale))
        path.lineToPoint_((54 * scale, size - 26 * scale))
        path.moveToPoint_((54 * scale, size - 26 * scale))
        path.lineToPoint_((42 * scale, size - 24 * scale))
    elif direction == "down":
        path.moveToPoint_((size - 28 * scale, size - 6 * scale))
        path.curveToPoint_controlPoint1_controlPoint2_(
            (size - 26 * scale, 6 * scale),
            (size - 14 * scale, size - 16 * scale),
            (size - 20 * scale, 12 * scale),
        )
        path.moveToPoint_((size - 14 * scale, 12 * scale))
        path.lineToPoint_((size - 26 * scale, 6 * scale))
        path.moveToPoint_((size - 26 * scale, 6 * scale))
        path.lineToPoint_((size - 24 * scale, 18 * scale))
    else:  # downRight
        path.moveToPoint_((8 * scale, size - 10 * scale))
        path.curveToPoint_controlPoint1_controlPoint2_(
            (46 * scale, size - 44 * scale),
            (20 * scale, size - 16 * scale),
            (32 * scale, size - 28 * scale),
        )
        path.moveToPoint_((38 * scale, size - 48 * scale))
        path.lineToPoint_((48 * scale, size - 46 * scale))
        path.moveToPoint_((48 * scale, size - 46 * scale))
        path.lineToPoint_((44 * scale, size - 36 * scale))

    v = _ShapeView.alloc().initWithFrame_path_color_stroke_(
        NSMakeRect(x, y, size, size), path, color, stroke,
    )
    return v


def hand_circle(x: float, y: float, w: float = 200, h: float = 110,
                color=None, stroke: float = 2.4) -> NSView:
    """Sketchy loop — used to highlight a word."""
    color = color or c(*ACCENT)
    sx = w / 200
    sy = h / 110
    path = NSBezierPath.bezierPath()
    path.moveToPoint_((100 * sx, (110 - 12) * sy))
    path.curveToPoint_controlPoint1_controlPoint2_(
        (192 * sx, (110 - 56) * sy),
        (160 * sx, (110 - 8) * sy),
        (196 * sx, (110 - 28) * sy),
    )
    path.curveToPoint_controlPoint1_controlPoint2_(
        (96 * sx, (110 - 100) * sy),
        (188 * sx, (110 - 90) * sy),
        (140 * sx, (110 - 102) * sy),
    )
    path.curveToPoint_controlPoint1_controlPoint2_(
        (12 * sx, (110 - 56) * sy),
        (44 * sx, (110 - 98) * sy),
        (10 * sx, (110 - 82) * sy),
    )
    path.curveToPoint_controlPoint1_controlPoint2_(
        (100 * sx, (110 - 10) * sy),
        (14 * sx, (110 - 28) * sy),
        (52 * sx, (110 - 12) * sy),
    )
    v = _ShapeView.alloc().initWithFrame_path_color_stroke_(
        NSMakeRect(x, y, w, h), path, color, stroke,
    )
    return v


# ── Custom button ──────────────────────────────────────────────────────────
# Replaces NSBezelStyleRounded chrome with layer-drawn terracotta pills.

class _ButtonBridge(NSObject):
    """Dispatches NSButton clicks to a Python callable keyed by tag."""

    def initWithMap_(self, mapping: dict) -> "_ButtonBridge":
        self = objc.super(_ButtonBridge, self).init()
        self._map = mapping
        return self

    def invoke_(self, sender) -> None:
        fn = self._map.get(sender.tag())
        if fn:
            fn()


def make_button(title: str, x: float, y: float, w: float, h: float,
                kind: str = "primary",
                bridge: Optional["_ButtonBridge"] = None,
                tag: int = 0,
                action: Optional[Callable] = None,
                enabled: bool = True,
                size: float = 13) -> NSButton:
    """Custom-styled button. kind: primary | secondary | ghost."""
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    btn.setBordered_(False)
    btn.setButtonType_(NSMomentaryLightButton)
    btn.setWantsLayer_(True)
    btn.setTag_(tag)

    fill = (ACCENT if enabled else ACCENT_W) if kind == "primary" else (
        CARD if kind == "secondary" else None
    )
    text_color = c(1, 1, 1, 1) if kind == "primary" else (
        c(*INK) if kind == "secondary" else c(*MUTED)
    )
    border_color = ACCENT_D if kind == "primary" else (
        LINE_STR if kind == "secondary" else None
    )

    layer = btn.layer()
    if fill:
        layer.setBackgroundColor_(c(*fill).CGColor())
    layer.setCornerRadius_(h / 2 if h <= 28 else 8)
    if border_color:
        layer.setBorderWidth_(0.5)
        layer.setBorderColor_(c(*border_color).CGColor())

    # Attributed title so we can set the color (NSButton.setTextColor_ doesn't exist).
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSTextAlignmentCenter)
    attrs = {
        NSFontAttributeName: font_sans(size, 0.23),
        NSForegroundColorAttributeName: text_color if enabled else c(*SUBTLE),
        NSParagraphStyleAttributeName: para,
    }
    attr_title = NSAttributedString.alloc().initWithString_attributes_(title, attrs)
    btn.setAttributedTitle_(attr_title)
    btn.setEnabled_(enabled)

    if bridge is not None and action is not None:
        bridge._map[tag] = action
        btn.setTarget_(bridge)
        btn.setAction_("invoke:")

    return btn


# ── Toggle ─────────────────────────────────────────────────────────────────

class _ToggleBridge(NSObject):
    def initWithState_onChange_(self, state: list,
                                on_change: Optional[Callable]) -> "_ToggleBridge":
        self = objc.super(_ToggleBridge, self).init()
        self._state = state
        self._on_change = on_change
        self._track: Optional[NSView] = None
        self._knob: Optional[NSView] = None
        return self

    def toggle_(self, sender) -> None:
        self._state[0] = not self._state[0]
        self._redraw()
        if self._on_change:
            self._on_change(self._state[0])

    def _redraw(self) -> None:
        if self._track is None or self._knob is None:
            return
        on = self._state[0]
        track_layer = self._track.layer()
        if on:
            track_layer.setBackgroundColor_(c(*ACCENT).CGColor())
            track_layer.setBorderColor_(c(*ACCENT_D).CGColor())
        else:
            track_layer.setBackgroundColor_(c(0.235, 0.200, 0.161, 0.18).CGColor())
            track_layer.setBorderColor_(c(*LINE).CGColor())
        # Slide knob
        kf = self._knob.frame()
        new_x = 18 if on else 2
        self._knob.setFrame_(NSMakeRect(new_x, 2, kf.size.width, kf.size.height))


def toggle(x: float, y: float, on: bool,
           on_change: Optional[Callable[[bool], None]]) -> NSView:
    """38×22 iOS-style toggle with a sliding white knob."""
    state = [on]
    bridge = _ToggleBridge.alloc().initWithState_onChange_(state, on_change)

    track = NSView.alloc().initWithFrame_(NSMakeRect(x, y, 38, 22))
    track.setWantsLayer_(True)
    tl = track.layer()
    tl.setCornerRadius_(11)
    tl.setBorderWidth_(0.5)

    if on:
        tl.setBackgroundColor_(c(*ACCENT).CGColor())
        tl.setBorderColor_(c(*ACCENT_D).CGColor())
    else:
        tl.setBackgroundColor_(c(0.235, 0.200, 0.161, 0.18).CGColor())
        tl.setBorderColor_(c(*LINE).CGColor())

    # Knob
    knob = NSView.alloc().initWithFrame_(
        NSMakeRect(18 if on else 2, 2, 18, 18)
    )
    knob.setWantsLayer_(True)
    kl = knob.layer()
    kl.setBackgroundColor_(c(1, 1, 1, 1).CGColor())
    kl.setCornerRadius_(9)
    kl.setShadowOpacity_(0.3)
    kl.setShadowOffset_((0, -1))
    kl.setShadowRadius_(2)
    track.addSubview_(knob)

    # Invisible click catcher
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 38, 22))
    btn.setButtonType_(NSMomentaryLightButton)
    btn.setBordered_(False)
    btn.setTitle_("")
    btn.setTarget_(bridge)
    btn.setAction_("toggle:")
    track.addSubview_(btn)

    bridge._track = track
    bridge._knob = knob
    track._bridge = bridge  # keep alive
    return track


# ── Keycap ─────────────────────────────────────────────────────────────────

def keycap(x: float, y: float, size: str = "xl",
           label_text: str = "⌥", sub: Optional[str] = "option",
           pressed: bool = False) -> NSView:
    """Warm gradient keycap with inner highlight and drop shadow."""
    dims = {
        "sm": (34, 34, 15, 8, 6),
        "md": (56, 56, 22, 9, 9),
        "lg": (88, 88, 34, 10, 14),
        "xl": (128, 128, 48, 11, 18),
    }[size]
    w, h, fs, sfs, radius = dims

    container = NSView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    container.setWantsLayer_(True)

    # Gradient layer
    grad = CAGradientLayer.layer()
    grad.setFrame_(NSMakeRect(0, 0, w, h))
    if pressed:
        grad.setColors_([c(*PAPER_D).CGColor(), c(*CARD).CGColor()])
    else:
        grad.setColors_([c(*CARD).CGColor(), c(*PAPER_D).CGColor()])
    grad.setCornerRadius_(radius)
    grad.setBorderWidth_(0.5)
    grad.setBorderColor_(c(*LINE_STR).CGColor())

    container.layer().addSublayer_(grad)
    container.layer().setCornerRadius_(radius)
    container.layer().setMasksToBounds_(False)

    if pressed:
        container.layer().setShadowColor_(c(*ACCENT).CGColor())
        container.layer().setShadowOpacity_(0.18)
        container.layer().setShadowRadius_(3)
        container.layer().setShadowOffset_((0, 0))
    else:
        container.layer().setShadowColor_(c(0.235, 0.157, 0.078, 1).CGColor())
        container.layer().setShadowOpacity_(0.12)
        container.layer().setShadowRadius_(4)
        container.layer().setShadowOffset_((0, -2))

    # Key label
    lbl = label(label_text, 0, h / 2 - fs / 2 - 2, w, fs + 8,
                size=fs, weight="medium",
                color=c(*ACCENT) if pressed else c(*INK_SOFT),
                align=NSCenterTextAlignment)
    container.addSubview_(lbl)

    if sub:
        sub_lbl = label(sub.upper(), 0, 8, w, sfs + 4,
                        size=sfs, weight="medium",
                        color=c(*ACCENT) if pressed else c(*SUBTLE),
                        align=NSCenterTextAlignment,
                        kern=1.5)
        container.addSubview_(sub_lbl)

    return container


# ── Stat / badge pill ──────────────────────────────────────────────────────

def pill(text: str, x: float, y: float, color=None,
         fg=None, size: float = 10) -> NSView:
    """Small rounded pill used for 'Active' badges and app tags."""
    # Rough width — layout can adjust afterwards.
    w = max(40, len(text) * (size - 2) + 14)
    h = size + 6
    v = rect(x, y, w, h, color=color or PAPER_D, radius=h / 2, border=LINE)
    v.addSubview_(label(text, 0, 1, w, size + 2,
                        size=size, weight="medium",
                        color=fg or c(*MUTED),
                        align=NSCenterTextAlignment))
    return v


# ── Visual-effect blur ─────────────────────────────────────────────────────

def blur_view(x: float, y: float, w: float, h: float,
              radius: float = 16, within_window: bool = False) -> NSVisualEffectView:
    v = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    v.setBlendingMode_(
        NSVisualEffectBlendingModeWithinWindow if within_window
        else NSVisualEffectBlendingModeBehindWindow
    )
    # Material 3 = NSVisualEffectMaterialSidebar (warm)
    try:
        v.setMaterial_(7)  # NSVisualEffectMaterialWindowBackground
    except Exception:
        pass
    v.setState_(1)  # NSVisualEffectStateActive
    v.setWantsLayer_(True)
    if radius:
        v.layer().setCornerRadius_(radius)
        v.layer().setMasksToBounds_(True)
    return v


# ── SVG-ish stack icon (for model cards) ───────────────────────────────────

def stack_icon(x: float, y: float, size: float = 20,
               color=None) -> NSView:
    """Two stacked rounded rectangles — matches dashboard model icon."""
    color = color or c(*MUTED)
    path = NSBezierPath.bezierPath()
    # Top rect
    path.appendBezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(size * 0.10, size * 0.65, size * 0.78, size * 0.20),
        1, 1,
    )
    # Bottom rect
    path.appendBezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(size * 0.10, size * 0.18, size * 0.78, size * 0.20),
        1, 1,
    )
    v = _ShapeView.alloc().initWithFrame_path_color_stroke_(
        NSMakeRect(x, y, size, size), path, color, 1.3,
    )
    return v


# Re-export NS constants that callers need so they don't reimport AppKit
NSCenterTextAlignment = NSCenterTextAlignment
NSLeftTextAlignment = NSLeftTextAlignment
NSRightTextAlignment = NSRightTextAlignment
