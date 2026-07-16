"""AI insights for a report's month-over-month comparison."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import cache, datasource, insights, profiles, report_defs

router = APIRouter(prefix="/insights", tags=["insights"])


@router.post("")
def get_insights(data: dict = Body(...)):
    key = data.get("reportKey")
    profile_id = data.get("profileId")
    cur = data.get("current") or {}
    prev = data.get("previous") or {}
    regenerate = bool(data.get("regenerate"))
    compare = data.get("compare", True)

    rdef = report_defs.get(key)
    if rdef is None:
        raise HTTPException(status_code=404, detail=f"Unknown report '{key}'")
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile '{profile_id}'")

    # Track how many times insights were regenerated for this exact view, so each
    # regeneration varies the prompt and overwrites the cache. Key on profile id
    # (not propertyId, which is empty for MoEngage profiles) + def signature.
    sig = report_defs.signature(rdef)
    var_key = "ttk:insights:var:" + cache.make_key(
        f"{key}:{compare}", profile["id"], f"{cur.get('start')}_{cur.get('end')}",
        f"{prev.get('start')}_{prev.get('end')}", sig,
    )
    cache_key = "ttk:insights:" + cache.make_key(
        f"{key}:{compare}", profile["id"], f"{cur.get('start')}_{cur.get('end')}",
        f"{prev.get('start')}_{prev.get('end')}", sig,
    )

    if not regenerate:
        cached = cache.get(cache_key)
        if cached is not None:
            return {"cached": True, **cached}

    variation = 0
    if regenerate:
        try:
            variation = cache.client().incr(var_key)
            cache.client().expire(var_key, 86400)
        except Exception:  # noqa: BLE001
            variation = 1

    try:
        report = datasource.run_comparison(
            rdef,
            profile,
            {"start": cur.get("start"), "end": cur.get("end"), "label": cur.get("label", "This period")},
            {"start": prev.get("start"), "end": prev.get("end"), "label": prev.get("label", "Previous period")},
            include_previous=compare,
        )
    except datasource.DataSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    result = insights.generate(report, variation=variation)
    cache.set(cache_key, result)
    return {"cached": False, **result}
