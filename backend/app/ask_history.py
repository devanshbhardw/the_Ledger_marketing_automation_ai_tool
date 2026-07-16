"""Saved Ask Q&A threads, persisted to ask_history.json on disk.

One entry per answered question: {profileId, question, answer, createdAt}.
Kept per profile, newest last, trimmed so the file can't grow unbounded.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

HISTORY_PATH = Path(os.environ.get("ASK_HISTORY_FILE", "ask_history.json"))

MAX_PER_PROFILE = 200


def _load() -> list[dict[str, Any]]:
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save(entries: list[dict[str, Any]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(entries, indent=2))


def add(profile_id: str, question: str, answer: str) -> dict[str, Any]:
    entries = _load()
    entry = {
        "profileId": profile_id,
        "question": question,
        "answer": answer,
        "createdAt": int(time.time()),
    }
    entries.append(entry)
    # Trim the oldest entries for this profile past the cap.
    mine = [e for e in entries if e.get("profileId") == profile_id]
    if len(mine) > MAX_PER_PROFILE:
        drop = set(map(id, mine[: len(mine) - MAX_PER_PROFILE]))
        entries = [e for e in entries if id(e) not in drop]
    _save(entries)
    return entry


def list_all(limit: int = 200) -> list[dict[str, Any]]:
    """Every saved Q&A across all profiles, newest first."""
    entries = _load()
    # File order is insertion order — it breaks ties for same-second entries.
    indexed = sorted(
        enumerate(entries),
        key=lambda t: (t[1].get("createdAt", 0), t[0]),
        reverse=True,
    )
    return [e for _, e in indexed[:limit]]


def list_for(profile_id: str, limit: int = 50) -> list[dict[str, Any]]:
    mine = [e for e in _load() if e.get("profileId") == profile_id]
    return mine[-limit:]


def clear(profile_id: str) -> int:
    entries = _load()
    remaining = [e for e in entries if e.get("profileId") != profile_id]
    removed = len(entries) - len(remaining)
    if removed:
        _save(remaining)
    return removed
