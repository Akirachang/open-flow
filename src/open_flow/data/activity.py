"""Activity log — append-only JSONL at ~/.local/share/open_flow/corrections.jsonl.

Each line is a JSON object:
    {timestamp, raw, cleaned, correction, app, latency}

'correction' is null until the user edits the post-inject toast.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOG_PATH = Path.home() / ".local" / "share" / "open_flow" / "corrections.jsonl"


@dataclass
class ActivityEntry:
    timestamp: float
    raw: str
    cleaned: str
    correction: Optional[str]
    app: str
    latency: float

    @property
    def ts_str(self) -> str:
        import datetime
        return datetime.datetime.fromtimestamp(self.timestamp).strftime("%-I:%M %p")


def log_path() -> Path:
    return _LOG_PATH


def append(entry: ActivityEntry) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
    except Exception:
        logger.exception("Failed to write activity entry")


def load_recent(n: int = 100) -> list[ActivityEntry]:
    if not _LOG_PATH.exists():
        return []
    try:
        lines = _LOG_PATH.read_text().strip().splitlines()
        entries = []
        for line in reversed(lines[-n * 2:]):
            try:
                d = json.loads(line)
                entries.append(ActivityEntry(**d))
            except Exception:
                continue
        return entries[:n]
    except Exception:
        logger.exception("Failed to read activity log")
        return []


def amend_correction(timestamp: float, correction: str) -> None:
    """Rewrite the log line whose timestamp matches, setting its correction field."""
    if not _LOG_PATH.exists():
        return
    try:
        lines = _LOG_PATH.read_text().splitlines()
        updated = []
        for line in lines:
            try:
                d = json.loads(line)
                if d.get("timestamp") == timestamp:
                    d["correction"] = correction
                    line = json.dumps(d)
            except Exception:
                pass
            updated.append(line)
        _LOG_PATH.write_text("\n".join(updated) + "\n")
    except Exception:
        logger.exception("Failed to amend correction")


def delete_entry(timestamp: float) -> None:
    if not _LOG_PATH.exists():
        return
    try:
        lines = _LOG_PATH.read_text().splitlines()
        kept = []
        for line in lines:
            try:
                d = json.loads(line)
                if d.get("timestamp") == timestamp:
                    continue
            except Exception:
                pass
            kept.append(line)
        _LOG_PATH.write_text("\n".join(kept) + "\n")
    except Exception:
        logger.exception("Failed to delete entry")


def reset_corrections() -> None:
    """Wipe correction fields from all entries (personalization reset)."""
    if not _LOG_PATH.exists():
        return
    try:
        lines = _LOG_PATH.read_text().splitlines()
        updated = []
        for line in lines:
            try:
                d = json.loads(line)
                d["correction"] = None
                line = json.dumps(d)
            except Exception:
                pass
            updated.append(line)
        _LOG_PATH.write_text("\n".join(updated) + "\n")
    except Exception:
        logger.exception("Failed to reset corrections")


def count_corrections() -> int:
    entries = load_recent(10000)
    return sum(1 for e in entries if e.correction)


def stats_today() -> dict:
    import datetime
    today = datetime.date.today()
    entries = load_recent(10000)
    today_entries = [
        e for e in entries
        if datetime.datetime.fromtimestamp(e.timestamp).date() == today
    ]
    latencies = [e.latency for e in today_entries if e.latency > 0]
    return {
        "count": len(today_entries),
        "avg_latency": sum(latencies) / len(latencies) if latencies else 0.0,
        "corrections": sum(1 for e in today_entries if e.correction),
    }
