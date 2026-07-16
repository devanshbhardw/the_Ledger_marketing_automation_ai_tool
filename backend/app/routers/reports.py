"""List the report template and run a single report for a given site profile."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query
from google.api_core.exceptions import GoogleAPIError

from .. import cache, datasource, ga4, profiles, report_defs

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("")
def list_reports():
    """The shared report template (sections shown on the dashboard)."""
    return {"reports": report_defs.all_reports(), "demo": ga4.demo_enabled()}


# Inline def — not part of the shared template, so it doesn't show up as a
# dashboard section. Powers the landing-page card sparklines.
_SPARKLINE_DEF = {
    "key": "_sparkline",
    "dimensions": ["date"],
    "metrics": ["sessions"],
    "orderBy": "date",
    "orderDesc": False,
    "limit": 7,
}


@router.get("/sparkline/{profile_id}")
def sparkline(profile_id: str):
    """Last 7 daily session counts for a site + when they were fetched."""
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile '{profile_id}'")

    cache_key = cache.make_key("_sparkline", profile["id"], "7daysAgo", "yesterday")
    cached = cache.get(cache_key)
    if cached is not None:
        return {"cached": True, **cached}

    try:
        data = datasource.run_report(_SPARKLINE_DEF, profile, "7daysAgo", "yesterday")
    except datasource.DataSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"GA4 Data API error: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    out = {"points": [r.get("sessions", 0) for r in data["rows"]],
           "fetchedAt": int(time.time())}
    cache.set(cache_key, out)
    return {"cached": False, **out}


@router.get("/{key}/compare")
def compare_report(
    key: str,
    profile_id: str = Query(..., alias="profileId"),
    cur_start: str = Query(..., alias="curStart"),
    cur_end: str = Query(..., alias="curEnd"),
    prev_start: str = Query(..., alias="prevStart"),
    prev_end: str = Query(..., alias="prevEnd"),
    cur_label: str = Query("This period", alias="curLabel"),
    prev_label: str = Query("Previous period", alias="prevLabel"),
    compare: bool = Query(True),
    refresh: bool = Query(False),
):
    rdef = report_defs.get(key)
    if rdef is None:
        raise HTTPException(status_code=404, detail=f"Unknown report '{key}'")
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile '{profile_id}'")

    # Key on the profile id (not propertyId, which is empty for MoEngage profiles).
    cache_key = cache.make_key(
        f"{key}:cmp:{compare}", profile["id"], f"{cur_start}_{cur_end}", f"{prev_start}_{prev_end}",
        report_defs.signature(rdef),
    )
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return {"cached": True, **cached}

    try:
        data = datasource.run_comparison(
            rdef,
            profile,
            {"start": cur_start, "end": cur_end, "label": cur_label},
            {"start": prev_start, "end": prev_end, "label": prev_label},
            include_previous=compare,
        )
    except datasource.DataSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"GA4 Data API error: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    cache.set(cache_key, data)
    return {"cached": False, **data}


@router.get("/{key}")
def get_report(
    key: str,
    profile_id: str = Query(..., alias="profileId"),
    start_date: str = Query("28daysAgo", alias="startDate"),
    end_date: str = Query("today", alias="endDate"),
    refresh: bool = Query(False, description="bypass cache"),
):
    rdef = report_defs.get(key)
    if rdef is None:
        raise HTTPException(status_code=404, detail=f"Unknown report '{key}'")

    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile '{profile_id}'")

    cache_key = cache.make_key(key, profile["id"], start_date, end_date, report_defs.signature(rdef))
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return {"cached": True, **cached}

    try:
        data = datasource.run_report(rdef, profile, start_date, end_date)
    except datasource.DataSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"GA4 Data API error: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    data["name"] = rdef.get("name", key)
    cache.set(cache_key, data)
    return {"cached": False, **data}
