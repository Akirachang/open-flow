#!/usr/bin/env python3
"""Generate OpenFlow.icns — white background with black waveform bars."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

PACKAGING = Path(__file__).parent
ICONSET   = PACKAGING / "OpenFlow.iconset"
ICNS_OUT  = PACKAGING / "OpenFlow.icns"

SIZES = [
    ("icon_16x16.png",        16),
    ("icon_16x16@2x.png",     32),
    ("icon_32x32.png",        32),
    ("icon_32x32@2x.png",     64),
    ("icon_128x128.png",     128),
    ("icon_128x128@2x.png",  256),
    ("icon_256x256.png",     256),
    ("icon_256x256@2x.png",  512),
    ("icon_512x512.png",     512),
    ("icon_512x512@2x.png", 1024),
]


def draw(size: int) -> "NSImage":
    from AppKit import NSBezierPath, NSColor, NSImage, NSMakeRect

    image = NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()

    # White rounded-rect background
    pad, r = size * 0.12, size * 0.22
    rect = NSMakeRect(pad, pad, size - 2 * pad, size - 2 * pad)
    bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, r, r)
    NSColor.whiteColor().setFill()
    bg.fill()

    # Black waveform bars
    NSColor.blackColor().setFill()
    heights = [0.28, 0.52, 0.72, 0.52, 0.28]
    bar_w   = size * 0.072
    gap     = size * 0.055
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x0      = (size - total_w) / 2
    for i, h in enumerate(heights):
        bh = size * h
        bx = x0 + i * (bar_w + gap)
        by = (size - bh) / 2
        p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(bx, by, bar_w, bh), bar_w / 2, bar_w / 2
        )
        p.fill()

    image.unlockFocus()
    return image


def save(img, path: Path) -> None:
    from AppKit import NSBitmapImageRep, NSPNGFileType
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(
        str(path), True
    )


def main() -> None:
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()

    for filename, size in SIZES:
        save(draw(size), ICONSET / filename)

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS_OUT)],
        check=True,
    )
    print(f"Written: {ICNS_OUT}")


if __name__ == "__main__":
    main()
