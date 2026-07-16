"""Background cache warming.

Re-runs the report template for every saved profile so the dashboard loads
instantly. Service-account auth means no user session is needed.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from . import cache, connections, datasource, jobs, profiles, report_defs
from .config import settings

log = logging.getLogger("ttk.scheduler")

DEFAULT_RANGE = ("28daysAgo", "today")


def refresh_all() -> None:
    start, end = DEFAULT_RANGE
    for profile in profiles.all_profiles():
        # OAuth-backed site: refresh its access token up front so every report
        # in this cycle reuses one fresh token. A dead refresh token (revoked,
        # expired, key rotated) skips just this site instead of failing each
        # report — and its cached data would be stale anyway.
        connection_id = (profile.get("connectionId") or "").strip()
        if connection_id:
            try:
                connections.get_valid_access_token(connection_id)
            except Exception as exc:  # noqa: BLE001 - keep the job alive
                log.warning(
                    "scheduler: skipping profile %s — could not refresh OAuth "
                    "connection %s: %s (re-authorize it on /connections)",
                    profile.get("id"), connection_id, exc,
                )
                continue
        for rdef in report_defs.all_reports():
            if not datasource.applicable(rdef, profile):
                continue  # profile lacks the creds/ids this report's source needs
            try:
                data = datasource.run_report(rdef, profile, start, end)
                # Key must match the routers exactly: profile id + def signature.
                key = cache.make_key(
                    rdef["key"], profile["id"], start, end, report_defs.signature(rdef)
                )
                cache.set(key, data)
            except Exception as exc:  # noqa: BLE001 - keep the job alive
                log.warning(
                    "scheduler: %s / %s failed: %s", profile.get("id"), rdef["key"], exc
                )
        log.info("scheduler: refreshed profile %s", profile.get("id"))


# --------------------------------------------------------------------------- #
# Scheduled per-site jobs (jobs.py)
# --------------------------------------------------------------------------- #
def _month_ranges(today: date) -> tuple[dict[str, str], dict[str, str]]:
    """Last full calendar month vs the one before, in the export payload shape."""
    first_of_this = today.replace(day=1)
    cur_end = first_of_this - timedelta(days=1)
    cur_start = cur_end.replace(day=1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)

    def rng(start: date, end: date) -> dict[str, str]:
        return {"start": start.isoformat(), "end": end.isoformat(),
                "label": start.strftime("%B %Y")}

    return rng(cur_start, cur_end), rng(prev_start, prev_end)


def _execute_job(job: dict) -> None:
    # The export router handlers are plain callables holding all the report
    # collection / demo / error handling; reuse them instead of duplicating.
    # (Imported here: routers import app modules, so a top-level import would
    # be a cycle risk if a router ever needs the scheduler.)
    from . import insights as insights_mod
    from .routers import export as export_router

    current, previous = _month_ranges(date.today())
    if job["type"] == "sheets_export":
        export_router.export_to_sheets(
            {"profileId": job["profileId"],
             "startDate": current["start"], "endDate": current["end"]}
        )
    elif job["type"] == "slides_export":
        export_router.export_to_slides(
            {"profileId": job["profileId"], "current": current, "previous": previous}
        )
    else:  # insights_digest — pre-generate into the same cache /insights reads
        profile = profiles.get(job["profileId"])
        if profile is None:
            raise RuntimeError(f"profile {job['profileId']} not found")
        for rdef in report_defs.all_reports():
            if not datasource.applicable(rdef, profile):
                continue
            report = datasource.run_comparison(rdef, profile, current, previous)
            result = insights_mod.generate(report)
            sig = report_defs.signature(rdef)
            cache_key = "ttk:insights:" + cache.make_key(
                f"{rdef['key']}:True", profile["id"],
                f"{current['start']}_{current['end']}",
                f"{previous['start']}_{previous['end']}", sig,
            )
            cache.set(cache_key, result)


def run_due_jobs() -> None:
    for job in jobs.due_jobs():
        try:
            _execute_job(job)
            log.info("jobs: ran %s (%s) for profile %s",
                     job["id"], job["type"], job["profileId"])
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            log.warning("jobs: %s (profile %s) failed: %s",
                        job["id"], job["profileId"], exc)
        finally:
            # Advance the schedule even on failure so a broken job waits for
            # its next slot instead of retrying every cycle.
            jobs.mark_run(job["id"])


_scheduler: BackgroundScheduler | None = None


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        refresh_all,
        "interval",
        minutes=settings.refresh_interval_min,
        id="refresh_all",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        run_due_jobs,
        "interval",
        minutes=settings.refresh_interval_min,
        id="run_due_jobs",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("scheduler started (every %s min)", settings.refresh_interval_min)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
