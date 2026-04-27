# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Open Flow."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all assets from native/heavy packages before Analysis runs
fw_datas, fw_binaries, fw_hiddenimports = collect_all("faster_whisper")
ct_datas, ct_binaries, ct_hiddenimports = collect_all("ctranslate2")
lc_datas, lc_binaries, lc_hiddenimports = collect_all("llama_cpp")

all_datas = [
    ("../src/open_flow/resources/welcome.html", "open_flow/resources"),
] + fw_datas + ct_datas + lc_datas

all_binaries = fw_binaries + ct_binaries + lc_binaries

all_hiddenimports = [
    # rumps / AppKit
    "rumps",
    "AppKit",
    "Foundation",
    "Cocoa",
    "objc",
    "PyObjCTools",
    "PyObjCTools.AppHelper",
    # AVFoundation for audio permissions
    "AVFoundation",
    # faster-whisper and its deps
    "faster_whisper",
    "faster_whisper.transcribe",
    "faster_whisper.audio",
    "faster_whisper.feature_extractor",
    "faster_whisper.tokenizer",
    "faster_whisper.utils",
    # llama-cpp
    "llama_cpp",
    # pynput
    "pynput",
    "pynput.keyboard",
    "pynput.keyboard._darwin",
    "pynput.mouse",
    "pynput.mouse._darwin",
    # sounddevice
    "sounddevice",
    # huggingface
    "huggingface_hub",
    # tomllib / tomli_w
    "tomllib",
    "tomli_w",
] + fw_hiddenimports + ct_hiddenimports + lc_hiddenimports

a = Analysis(
    ["../src/open_flow/__main__.py"],
    pathex=["../src"],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Open Flow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Open Flow",
)

app = BUNDLE(
    coll,
    name="Open Flow.app",
    icon=str(Path(SPECPATH) / "OpenFlow.icns"),
    bundle_identifier="com.openflow.app",
    info_plist={
        "CFBundleName": "Open Flow",
        "CFBundleDisplayName": "Open Flow",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": "Open Flow needs microphone access to transcribe your speech.",
        "NSPrincipalClass": "NSApplication",
    },
)
