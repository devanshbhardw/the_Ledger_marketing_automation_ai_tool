"""Scheduled per-site jobs, persisted to jobs.json on disk.

A job is one recurring action for one site (see scheduler.run_due_jobs):

  id          stable slug (profileId + type, deduped)
  profileId   the site this job runs for
  type        "sheets_export" | "slides_export" | "insights_digest"
  frequency   "daily" | "weekly" | "monthly"
  hour        0-23, local server time
  enabled     bool
  lastRunAt   unix epoch seconds of the last attempt (0 = never)
  nextRunAt   unix epoch seconds of the next due run
  createdAt   unix epoch seconds

Schedule anchors: daily runs every day at `hour`; weekly on Mondays; monthly
on the 1st — so a monthly job reports on the just-finished calendar month.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

JOBS_PATH = Path(os.environ.get("JOBS_FILE", "jobs.json"))

TYPES = ("sheets_export", "slides_export", "insights_digest")
FREQUENCIES = ("daily", "weekly", "monthly")


def _load() -> list[dict[str, Any]]:
    if JOBS_PATH.exists():
        try:
            data = json.loads(JOBS_PATH.read_text())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save(jobs: list[dict[str, Any]]) -> None:
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOBS_PATH.write_text(json.dumps(jobs, indent=2))


def compute_next_run(frequency: str, hour: int, now: float | None = None) -> int:
    """Epoch seconds of the next run strictly after `now` (local server time)."""
    ref = datetime.fromtimestamp(now if now is not None else time.time())
    candidate = ref.replace(hour=hour, minute=0, second=0, microsecond=0)
    if frequency == "daily":
        if candidate <= ref:
            candidate += timedelta(days=1)
    elif frequency == "weekly":
        candidate += timedelta(days=(0 - candidate.weekday()) % 7)  # next Monday
        if candidate <= ref:
            candidate += timedelta(days=7)
    else:  # monthly — the 1st
        candidate = candidate.replace(day=1)
        if candidate <= ref:
            candidate = (candidate.replace(day=28) + timedelta(days=4)).replace(day=1)
    return int(candidate.timestamp())


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    profile_id = (data.get("profileId") or "").strip()
    jtype = (data.get("type") or "").strip()
    frequency = (data.get("frequency") or "daily").strip()
    if not profile_id:
        raise ValueError("profileId is required")
    if jtype not in TYPES:
        raise ValueError(f"type must be one of {list(TYPES)}")
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of {list(FREQUENCIES)}")
    try:
        hour = int(data.get("hour", 8))
    except (TypeError, ValueError):
        raise ValueError("hour must be an integer 0-23")
    if not 0 <= hour <= 23:
        raise ValueError("hour must be an integer 0-23")
    return {
        "profileId": profile_id,
        "type": jtype,
        "frequency": frequency,
        "hour": hour,
        "enabled": bool(data.get("enabled", True)),
    }


def create(data: dict[str, Any]) -> dict[str, Any]:
    jobs = _load()
    fields = _validate(data)

    base = f"{fields['profileId']}-{fields['type']}"
    jid = base
    n = 2
    existing = {j["id"] for j in jobs}
    while jid in existing:
        jid = f"{base}-{n}"
        n += 1

    now = int(time.time())
    job = {
        "id": jid,
        **fields,
        "lastRunAt": 0,
        "nextRunAt": compute_next_run(fields["frequency"], fields["hour"], now),
        "createdAt": now,
    }
    jobs.append(job)
    _save(jobs)
    return job


def all_jobs(profile_id: str | None = None) -> list[dict[str, Any]]:
    jobs = _load()
    if profile_id:
        jobs = [j for j in jobs if j.get("profileId") == profile_id]
    return jobs


def get(job_id: str) -> dict[str, Any] | None:
    return next((j for j in _load() if j.get("id") == job_id), None)


def update(job_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    jobs = _load()
    for i, j in enumerate(jobs):
        if j["id"] == job_id:
            fields = _validate({**j, **data})
            job = {
                "id": job_id,
                **fields,
                "lastRunAt": j.get("lastRunAt", 0),
                # Schedule params may have changed — recompute from now.
                "nextRunAt": compute_next_run(fields["frequency"], fields["hour"]),
                "createdAt": j.get("createdAt", int(time.time())),
            }
            jobs[i] = job
            _save(jobs)
            return job
    return None


def delete(job_id: str) -> bool:
    jobs = _load()
    remaining = [j for j in jobs if j["id"] != job_id]
    if len(remaining) == len(jobs):
        return False
    _save(remaining)
    return True


def due_jobs(now: float | None = None) -> list[dict[str, Any]]:
    ts = now if now is not None else time.time()
    return [
        j for j in _load()
        if j.get("enabled") and 0 < int(j.get("nextRunAt") or 0) <= ts
    ]


def mark_run(job_id: str, now: float | None = None) -> None:
    """Record an attempt (success or failure) and advance nextRunAt, so a
    failing job waits for its next slot instead of retrying every cycle."""
    ts = int(now if now is not None else time.time())
    jobs = _load()
    for j in jobs:
        if j["id"] == job_id:
            j["lastRunAt"] = ts
            j["nextRunAt"] = compute_next_run(j["frequency"], j["hour"], ts)
            _save(jobs)
            return
