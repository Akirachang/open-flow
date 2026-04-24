"""Dashboard window — Activity / Settings / Personalization / Models tabs.

Layout matches the Claude-aesthetic reference design:
- Horizontal tab bar at the top (NOT a vertical sidebar)
- Paper grain overlay on the window background
- Serif headlines, mono timestamps, terracotta accents
- Card-based content with hairline dividers
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSCenterTextAlignment,
    NSColor,
    NSFont,
    NSLeftTextAlignment,
    NSMakeRect,
    NSRightTextAlignment,
    NSScreen,
    NSScrollView,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRange

from open_flow.ui.design import (
    ACCENT, ACCENT_D, ACCENT_I, ACCENT_W,
    CARD, GOOD, INK, INK_SOFT, LINE, LINE_H, LINE_STR,
    MUTED, PAPER, PAPER_D, SUBTLE, WARN,
    _ButtonBridge,
    apply_grain,
    c,
    font_sans,
    gradient_rect,
    label,
    make_button,
    pill,
    rect,
    stack_icon,
    toggle,
)

logger = logging.getLogger(__name__)

_W, _H = 960, 640
_PAD = 32
_TAB_BAR_H = 48
_CONTENT_TOP_PAD = 32

_TABS = ["Activity", "Settings", "Personalization", "Models"]


# Helper: scrollable content container
def _scroll_view(x: float, y: float, w: float, h: float) -> tuple[NSScrollView, NSView]:
    sv = NSScrollView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    sv.setHasVerticalScroller_(True)
    sv.setHasHorizontalScroller_(False)
    sv.setAutohidesScrollers_(True)
    sv.setBorderType_(0)
    sv.setDrawsBackground_(False)
    doc = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w - 16, h))
    sv.setDocumentView_(doc)
    return sv, doc


class Dashboard:
    def __init__(self, cfg, save_cfg: Callable) -> None:
        self._cfg = cfg
        self._save_cfg = save_cfg
        self._window: NSWindow | None = None
        self._bridge: _ButtonBridge | None = None
        self._next_tag = 1
        self._content: NSView | None = None
        self._current_tab = "Activity"
        self._tab_btns: dict[str, NSButton] = {}

    def show(self) -> None:
        if self._window is None:
            self._build()
        self._window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    # ── Build ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        screen = NSScreen.mainScreen()
        sf = screen.frame()
        x = (sf.size.width - _W) / 2
        y = (sf.size.height - _H) / 2

        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                 NSWindowStyleMaskMiniaturizable)
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

        self._build_tab_bar(cv)

        # Content area under the tab bar
        content_h = _H - _TAB_BAR_H
        self._content = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _W, content_h)
        )
        cv.addSubview_(self._content)

        self._switch_tab("Activity")

    def _build_tab_bar(self, cv: NSView) -> None:
        bar_y = _H - _TAB_BAR_H
        # Hairline divider at bottom of tab bar
        cv.addSubview_(rect(0, bar_y, _W, 0.5, color=(*INK_SOFT[:3], 0.12)))

        x_cursor = 16
        for tab in _TABS:
            btn_w = 140
            btn = self._tab_button(tab, x_cursor, bar_y + 8, btn_w, 32)
            cv.addSubview_(btn)
            self._tab_btns[tab] = btn
            x_cursor += btn_w + 4

        # Right side: status indicator
        status_w = 100
        cv.addSubview_(rect(_W - status_w - 16, bar_y + 18, 6, 6,
                            color=GOOD, radius=3))
        cv.addSubview_(label("idle", _W - status_w - 4, bar_y + 14, status_w,
                             14, size=10.5, weight="mono", color=c(*SUBTLE)))

    def _tab_button(self, tab: str, x: float, y: float, w: float, h: float) -> NSButton:
        tag = self._next_tag
        self._next_tag += 1
        self._bridge._map[tag] = lambda t=tab: self._switch_tab(t)

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        btn.setBordered_(False)
        btn.setWantsLayer_(True)
        btn.setTag_(tag)
        btn.setTarget_(self._bridge)
        btn.setAction_("invoke:")
        return btn

    def _style_tab(self, btn: NSButton, title: str, active: bool) -> None:
        from AppKit import (
            NSAttributedString,
            NSFontAttributeName,
            NSForegroundColorAttributeName,
            NSParagraphStyleAttributeName,
            NSMutableParagraphStyle,
            NSTextAlignmentCenter,
        )
        btn.layer().setCornerRadius_(8)
        if active:
            btn.layer().setBackgroundColor_(c(*ACCENT_W).CGColor())
            btn.layer().setBorderWidth_(0.5)
            btn.layer().setBorderColor_(c(*ACCENT, 0.25 if False else ACCENT_D[3] * 0.3).CGColor())
            text_color = c(*ACCENT_I)
            weight = 0.4
        else:
            btn.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
            btn.layer().setBorderWidth_(0)
            text_color = c(*MUTED)
            weight = 0.23

        para = NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(NSTextAlignmentCenter)
        attrs = {
            NSFontAttributeName: font_sans(13, weight),
            NSForegroundColorAttributeName: text_color,
            NSParagraphStyleAttributeName: para,
        }
        attr_str = NSAttributedString.alloc().initWithString_attributes_(title, attrs)
        btn.setAttributedTitle_(attr_str)

    def _switch_tab(self, tab: str) -> None:
        self._current_tab = tab
        for t, btn in self._tab_btns.items():
            self._style_tab(btn, t, t == tab)

        # Clear previous content
        for sub in list(self._content.subviews()):
            sub.removeFromSuperview()

        getattr(self, f"_render_{tab.lower()}")()

    # ── Shared: page header ──────────────────────────────────────────────

    def _page_header(self, title: str, subtitle: str, meta: str = "") -> float:
        """Draw h1 + subtitle at top of content area. Returns the y just below them."""
        top = self._content.frame().size.height
        self._content.addSubview_(label(
            title, _PAD, top - _CONTENT_TOP_PAD - 32, 600, 36,
            size=28, weight="serif", color=c(*INK_SOFT),
        ))
        if meta:
            self._content.addSubview_(label(
                meta, _W - _PAD - 280, top - _CONTENT_TOP_PAD - 22, 280, 14,
                size=11, weight="mono", color=c(*SUBTLE),
                align=NSRightTextAlignment,
            ))
        self._content.addSubview_(label(
            subtitle, _PAD, top - _CONTENT_TOP_PAD - 56, _W - _PAD * 2, 16,
            size=13, color=c(*MUTED),
        ))
        return top - _CONTENT_TOP_PAD - 72

    # ── Activity tab ─────────────────────────────────────────────────────

    def _render_activity(self) -> None:
        from open_flow.data import activity as act_module

        stats = act_module.stats_today()
        entries = act_module.load_recent(100)
        corrections_total = act_module.count_corrections()
        cleaned_today = max(0, stats["count"] - stats.get("corrections", 0))

        meta = f"{stats['count']} today · {len(entries)} stored"
        y = self._page_header("Activity",
                              "Recent dictations, transcripts, and latencies.",
                              meta=meta)

        # 4 stat cards
        stat_data = [
            ("Today", str(stats["count"]), "dictations"),
            ("Avg latency", f"{stats['avg_latency']:.2f}s", "to inject"),
            ("Cleaned", str(cleaned_today), "by LLM"),
            ("Corrections", str(corrections_total), "total"),
        ]
        gap = 12
        card_w = (_W - _PAD * 2 - gap * 3) / 4
        card_y = y - 70
        for i, (l, v, sub) in enumerate(stat_data):
            cx = _PAD + i * (card_w + gap)
            card = rect(cx, card_y, card_w, 68, color=CARD, radius=10,
                        border=(*INK_SOFT[:3], 0.10))
            self._content.addSubview_(card)
            card.addSubview_(label(l.upper(), 14, 46, card_w - 28, 12,
                                   size=9, weight="medium", color=c(*SUBTLE),
                                   kern=1.2))
            card.addSubview_(label(v, 14, 16, card_w - 28, 28,
                                   size=24, weight="serif", color=c(*INK_SOFT)))
            card.addSubview_(label(sub, 14, 2, card_w - 28, 12,
                                   size=10, weight="mono", color=c(*MUTED)))

        # "RECENT" label
        recent_y = card_y - 32
        self._content.addSubview_(label("RECENT", _PAD, recent_y, 200, 12,
                                        size=9, weight="medium", color=c(*SUBTLE),
                                        kern=1.4))

        # Outer card container for the list
        list_top = recent_y - 6
        list_bottom = 12
        list_h = list_top - list_bottom
        outer = rect(_PAD, list_bottom, _W - _PAD * 2, list_h,
                     color=CARD, radius=10, border=(*INK_SOFT[:3], 0.10))
        self._content.addSubview_(outer)

        # Scroll inside the outer card
        sv, doc = _scroll_view(1, 1, _W - _PAD * 2 - 2, list_h - 2)
        outer.addSubview_(sv)

        if not entries:
            doc.setFrame_(NSMakeRect(0, 0, _W - _PAD * 2 - 2, list_h - 2))
            doc.addSubview_(label("No dictations yet.",
                                  0, (list_h - 2) / 2 - 10,
                                  _W - _PAD * 2 - 2, 20, size=13,
                                  color=c(*MUTED),
                                  align=NSCenterTextAlignment))
            return

        row_h = 56
        total_h = max(list_h - 2, len(entries) * row_h)
        doc.setFrame_(NSMakeRect(0, 0, _W - _PAD * 2 - 18, total_h))

        for i, entry in enumerate(entries):
            ry = total_h - (i + 1) * row_h
            row = NSView.alloc().initWithFrame_(
                NSMakeRect(0, ry, _W - _PAD * 2 - 18, row_h)
            )
            doc.addSubview_(row)

            # Bottom hairline divider (skip last)
            if i < len(entries) - 1:
                row.addSubview_(rect(18, 0, _W - _PAD * 2 - 54, 1,
                                     color=LINE_H))

            row.addSubview_(label(entry.ts_str, 18, row_h - 22, 64, 14,
                                  size=10.5, weight="mono", color=c(*SUBTLE)))

            cleaned = entry.cleaned[:80] + ("…" if len(entry.cleaned) > 80 else "")
            row.addSubview_(label(cleaned, 90, row_h - 22, _W - _PAD * 2 - 260, 16,
                                  size=13, color=c(*INK)))

            raw_preview = entry.raw[:80] + ("…" if len(entry.raw) > 80 else "")
            row.addSubview_(label(f"raw: {raw_preview}", 90, row_h - 42,
                                  _W - _PAD * 2 - 260, 14,
                                  size=10.5, weight="mono", color=c(*SUBTLE)))

            # Right side: latency + app pill
            lat_color = GOOD if entry.latency < 1.0 else WARN
            row.addSubview_(label(f"{entry.latency:.2f}s",
                                  _W - _PAD * 2 - 158, row_h - 22, 56, 14,
                                  size=11, weight="mono", color=c(*lat_color),
                                  align=NSRightTextAlignment))

            # App pill badge
            app_pill = pill(entry.app, _W - _PAD * 2 - 98, row_h - 22,
                            color=PAPER_D, fg=c(*MUTED), size=10)
            row.addSubview_(app_pill)

            if entry.correction:
                row.addSubview_(rect(_W - _PAD * 2 - 30, row_h / 2 - 3, 6, 6,
                                     color=WARN, radius=3))

    # ── Settings tab ─────────────────────────────────────────────────────

    def _render_settings(self) -> None:
        y = self._page_header("Settings",
                              "Tune the hotkey, audio source, and behavior.")

        # Add a tiny state holder so nested closures can mutate config
        def _save_toggle(key: str):
            def handler(new_val: bool) -> None:
                setattr(self._cfg, key, new_val)
                self._save_cfg(self._cfg)
            return handler

        sections = [
            ("INPUT", [
                ("Hotkey", "Hold to record. Release to transcribe.", "hotkey", None),
                ("Microphone", None, "text", "MacBook Pro Microphone"),
                ("Voice activity detection",
                 "Trim silence from the start and end of each clip.",
                 "text", "Always on"),
            ]),
            ("PROCESSING", [
                ("LLM cleanup",
                 "Fix punctuation, capitalization, and remove filler.",
                 "toggle", ("llm_enabled", _save_toggle("llm_enabled"))),
                ("Transcription model", None, "text", "distil-large-v3 · int8"),
                ("Cleanup model", None, "text", self._cfg.llm_model),
            ]),
            ("BEHAVIOR", [
                ("Recording HUD",
                 "Show the waveform overlay while recording.",
                 "text", "On"),
                ("Launch at login", None, "text", "Off"),
            ]),
        ]

        for heading, rows in sections:
            y -= 20
            self._content.addSubview_(label(heading, _PAD, y, 200, 12,
                                            size=9, weight="medium",
                                            color=c(*SUBTLE), kern=1.4))
            y -= 6

            for row_label, sub, kind, payload in rows:
                row_h = 54 if sub else 42
                y -= row_h

                # Label column
                lbl_y = y + (row_h - (20 if sub else 18)) / 2 + (9 if sub else 0)
                self._content.addSubview_(label(
                    row_label, _PAD, lbl_y if sub else y + (row_h - 18) / 2,
                    340, 18, size=13.5, weight="medium", color=c(*INK),
                ))
                if sub:
                    self._content.addSubview_(label(
                        sub, _PAD, y + 8, 460, 14,
                        size=11, color=c(*MUTED),
                    ))

                # Widget column (right)
                if kind == "toggle":
                    cfg_key, handler = payload
                    current = getattr(self._cfg, cfg_key, False)
                    tg = toggle(_W - _PAD - 38, y + (row_h - 22) / 2,
                                current, handler)
                    self._content.addSubview_(tg)
                elif kind == "hotkey":
                    hk_display = self._cfg.hotkey.replace("_", " ").title()
                    hk_view = rect(_W - _PAD - 140, y + (row_h - 28) / 2,
                                   140, 28, color=CARD, radius=7,
                                   border=(*INK_SOFT[:3], 0.22))
                    self._content.addSubview_(hk_view)
                    hk_view.addSubview_(label(hk_display, 8, 6, 124, 16,
                                              size=12, weight="mono",
                                              color=c(*INK_SOFT),
                                              align=NSCenterTextAlignment))
                elif kind == "text":
                    self._content.addSubview_(label(
                        str(payload), _W - _PAD - 300,
                        y + (row_h - 16) / 2,
                        300, 16, size=11.5, weight="mono",
                        color=c(*MUTED), align=NSRightTextAlignment,
                    ))

                # Hairline
                self._content.addSubview_(rect(_PAD, y, _W - _PAD * 2, 1,
                                               color=LINE_H))

    # ── Personalization tab ──────────────────────────────────────────────

    def _render_personalization(self) -> None:
        from open_flow.data import activity as act_module

        y = self._page_header(
            "Personalization",
            "Open Flow learns from edits you make after dictation. Corrections become few-shot examples on every cleanup.",
        )

        entries = act_module.load_recent(10000)
        corrections = [e for e in entries if e.correction]
        count = len(corrections)
        progress = min(1.0, count / 200)

        # Gradient progress card
        card_y = y - 80
        card_w = _W - _PAD * 2
        prog_card = gradient_rect(_PAD, card_y, card_w, 72,
                                  CARD, PAPER_D, radius=12)
        prog_card.layer().setBorderWidth_(0.5)
        prog_card.layer().setBorderColor_(c(*LINE).CGColor())
        self._content.addSubview_(prog_card)

        prog_card.addSubview_(label(
            f"{count} / 200 CORRECTIONS", 20, 46, 300, 14,
            size=10, weight="medium", color=c(*ACCENT), kern=1.5,
        ))
        prog_card.addSubview_(label(
            "Keep correcting to unlock fine-tuning.", 20, 24, 420, 18,
            size=14, weight="serif", color=c(*INK_SOFT),
        ))
        prog_card.addSubview_(label(
            f"At 200 corrections you can train a personal LoRA adapter.",
            20, 8, 480, 14, size=11, color=c(*MUTED),
        ))

        # Progress bar (right side)
        bar_x = card_w - 220
        bar_track = rect(bar_x, 32, 200, 6, color=(*INK_SOFT[:3], 0.10), radius=3)
        prog_card.addSubview_(bar_track)
        fill_w = max(4, 200 * progress)
        bar_fill = gradient_rect(0, 0, fill_w, 6, ACCENT_D, ACCENT, radius=3)
        bar_track.addSubview_(bar_fill)
        prog_card.addSubview_(label(
            f"{int(progress * 100)}%", card_w - 40, 14, 30, 12,
            size=10, weight="mono", color=c(*SUBTLE),
            align=NSRightTextAlignment,
        ))

        # Header bar
        hdr_y = card_y - 32
        self._content.addSubview_(label(
            "CORRECTION LOG", _PAD, hdr_y, 200, 12,
            size=9, weight="medium", color=c(*SUBTLE), kern=1.4,
        ))

        tag = self._next_tag
        self._next_tag += 1
        reset_btn = make_button("Reset personalization",
                                _W - _PAD - 150, hdr_y - 6, 150, 22,
                                kind="ghost", bridge=self._bridge, tag=tag,
                                action=lambda: self._reset_personalization(),
                                size=11)
        self._content.addSubview_(reset_btn)

        # List
        list_top = hdr_y - 18
        list_h = list_top - 12
        sv, doc = _scroll_view(_PAD, 12, _W - _PAD * 2, list_h)
        self._content.addSubview_(sv)

        if not corrections:
            doc.setFrame_(NSMakeRect(0, 0, _W - _PAD * 2 - 16, list_h))
            doc.addSubview_(label(
                "No corrections yet.\nDictate, then edit the toast to teach Open Flow your style.",
                0, list_h / 2 - 20, _W - _PAD * 2 - 16, 40,
                size=13, color=c(*MUTED), align=NSCenterTextAlignment,
            ))
            return

        row_h = 92
        total_h = max(list_h, len(corrections) * row_h)
        doc.setFrame_(NSMakeRect(0, 0, _W - _PAD * 2 - 18, total_h))

        for i, entry in enumerate(reversed(corrections)):
            ry = total_h - (i + 1) * row_h

            card = rect(0, ry + 4, _W - _PAD * 2 - 18, row_h - 8,
                        color=CARD, radius=10, border=(*INK_SOFT[:3], 0.10))
            doc.addSubview_(card)

            card.addSubview_(label(entry.ts_str, 16, row_h - 28, 80, 12,
                                   size=10, weight="mono", color=c(*SUBTLE)))

            # Delete (X) button
            tag = self._next_tag
            self._next_tag += 1
            ts = entry.timestamp
            del_btn = make_button("✕ Delete",
                                  _W - _PAD * 2 - 18 - 86, row_h - 32, 70, 22,
                                  kind="ghost", bridge=self._bridge, tag=tag,
                                  action=lambda t=ts: self._delete_correction(t),
                                  size=10)
            card.addSubview_(del_btn)

            # Two-column content
            half = (_W - _PAD * 2 - 18 - 48) / 2
            card.addSubview_(label("CLEANED", 16, row_h - 52, half, 12,
                                   size=9, weight="medium", color=c(*SUBTLE),
                                   kern=1.2))
            card.addSubview_(label(entry.cleaned, 16, row_h - 76, half, 20,
                                   size=12, color=c(*MUTED),
                                   strikethrough=True))

            # Arrow
            card.addSubview_(label("→", 16 + half + 8, row_h - 70, 20, 20,
                                   size=16, color=c(*ACCENT),
                                   align=NSCenterTextAlignment))

            card.addSubview_(label("YOUR EDIT", 16 + half + 32, row_h - 52,
                                   half, 12, size=9, weight="medium",
                                   color=c(*ACCENT), kern=1.2))
            card.addSubview_(label(entry.correction or "",
                                   16 + half + 32, row_h - 76, half, 20,
                                   size=12, color=c(*INK)))

    def _reset_personalization(self) -> None:
        from open_flow.data import activity as act_module
        act_module.reset_corrections()
        self._switch_tab("Personalization")

    def _delete_correction(self, timestamp: float) -> None:
        from open_flow.data import activity as act_module
        act_module.delete_entry(timestamp)
        self._switch_tab("Personalization")

    # ── Models tab ───────────────────────────────────────────────────────

    def _render_models(self) -> None:
        y = self._page_header("Models", "All models run locally on your Mac.")

        whisper_exists = self._cfg.whisper_model_path.exists()
        llm_exists = self._cfg.llm_model_path.exists()
        used_gb = (1.5 if whisper_exists else 0) + (2.0 if llm_exists else 0)
        total_gb = 8.0
        ratio = used_gb / total_gb

        # Disk usage card
        disk_y = y - 64
        card_w = _W - _PAD * 2
        disk_card = rect(_PAD, disk_y, card_w, 56,
                         color=CARD, radius=10, border=(*INK_SOFT[:3], 0.10))
        self._content.addSubview_(disk_card)
        disk_card.addSubview_(label("DISK USAGE", 16, 36, 200, 12,
                                    size=9, weight="medium",
                                    color=c(*SUBTLE), kern=1.4))
        # Split progress bar: whisper + llm in different shades
        track = rect(16, 16, card_w - 150, 6,
                     color=(*INK_SOFT[:3], 0.10), radius=3)
        disk_card.addSubview_(track)
        if whisper_exists:
            wshare = 1.5 / total_gb * (card_w - 150)
            track.addSubview_(rect(0, 0, wshare, 6, color=ACCENT_D, radius=3))
        if llm_exists:
            offset = (1.5 if whisper_exists else 0) / total_gb * (card_w - 150)
            lshare = 2.0 / total_gb * (card_w - 150)
            track.addSubview_(rect(offset, 0, lshare, 6,
                                   color=(*ACCENT[:3], 0.7), radius=3))
        disk_card.addSubview_(label(f"{used_gb:.2f} / {total_gb:.2f} GB",
                                    card_w - 130, 14, 114, 14,
                                    size=11, weight="mono", color=c(*MUTED),
                                    align=NSRightTextAlignment))

        models = [
            {
                "name": "distil-large-v3 · int8",
                "role": "Transcription",
                "size": "1.5 GB",
                "sub": "fastest · balanced accuracy",
                "installed": whisper_exists, "active": whisper_exists,
            },
            {
                "name": "whisper-large-v3-turbo · q4",
                "role": "Transcription",
                "size": "0.95 GB",
                "sub": "smaller · slightly less accurate",
                "installed": False, "active": False,
            },
            {
                "name": "Qwen2.5-3B-Instruct Q4",
                "role": "Cleanup LLM",
                "size": "1.95 GB",
                "sub": "recommended · multilingual",
                "installed": llm_exists, "active": llm_exists,
            },
            {
                "name": "Phi-3-mini · Q4",
                "role": "Cleanup LLM",
                "size": "2.10 GB",
                "sub": "alternative · English-only",
                "installed": False, "active": False,
            },
        ]

        # Scrollable list below the disk card
        list_top = disk_y - 16
        list_h = list_top - 12
        sv, doc = _scroll_view(_PAD, 12, _W - _PAD * 2, list_h)
        self._content.addSubview_(sv)

        card_h = 72
        gap = 10
        total_h = max(list_h, len(models) * (card_h + gap))
        doc.setFrame_(NSMakeRect(0, 0, _W - _PAD * 2 - 18, total_h))

        for i, m in enumerate(models):
            ry = total_h - (i + 1) * (card_h + gap) + gap
            border = ACCENT_W if m["active"] else (*INK_SOFT[:3], 0.10)
            card = rect(0, ry, _W - _PAD * 2 - 18, card_h,
                        color=CARD, radius=10, border=border)
            doc.addSubview_(card)

            # Icon badge
            icon_bg = rect(16, (card_h - 40) / 2, 40, 40,
                           color=ACCENT_W if m["active"] else PAPER_D,
                           radius=8,
                           border=(*ACCENT[:3], 0.25) if m["active"]
                                  else (*INK_SOFT[:3], 0.10))
            card.addSubview_(icon_bg)
            icon_bg.addSubview_(stack_icon(10, 10, size=20,
                                           color=c(*ACCENT) if m["active"]
                                                 else c(*MUTED)))

            # Name row
            card.addSubview_(label(m["name"], 68, card_h - 28, 380, 18,
                                   size=13, weight="mono", color=c(*INK)))

            if m["active"]:
                badge_x = 68 + _approx_text_width(m["name"], 13, mono=True) + 10
                card.addSubview_(pill("Active", badge_x, card_h - 26,
                                      color=ACCENT_W, fg=c(*ACCENT_I), size=9))

            card.addSubview_(label(
                f"{m['role']} · {m['size']} · {m['sub']}",
                68, card_h - 48, 460, 14,
                size=10.5, weight="mono", color=c(*SUBTLE),
            ))

            # Right action button
            tag = self._next_tag
            self._next_tag += 1
            if m["installed"]:
                if m["active"]:
                    btn = make_button("In use", _W - _PAD * 2 - 18 - 90,
                                      (card_h - 24) / 2, 74, 24,
                                      kind="secondary", enabled=False,
                                      bridge=self._bridge, tag=tag,
                                      action=lambda: None, size=11)
                else:
                    btn = make_button("Swap", _W - _PAD * 2 - 18 - 90,
                                      (card_h - 24) / 2, 74, 24,
                                      kind="secondary",
                                      bridge=self._bridge, tag=tag,
                                      action=lambda: None, size=11)
            else:
                btn = make_button("Download", _W - _PAD * 2 - 18 - 94,
                                  (card_h - 24) / 2, 78, 24,
                                  kind="primary",
                                  bridge=self._bridge, tag=tag,
                                  action=lambda: None, size=11)
            card.addSubview_(btn)


def _approx_text_width(text: str, size: float, mono: bool = False) -> float:
    factor = 0.62 if mono else 0.55
    return len(text) * size * factor
