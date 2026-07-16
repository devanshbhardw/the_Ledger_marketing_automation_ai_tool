

"""Export all reports for a site to its Google Sheet — one tab per report."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from google.api_core.exceptions import GoogleAPIError
from googleapiclient.errors import HttpError

from .. import cache, datasource, ga4, insights as insights_mod, profiles, report_defs, sheets, slides

router = APIRouter(prefix="/export", tags=["export"])


def _google_http_error(service: str, exc: HttpError) -> HTTPException:
    """Turn a googleapiclient HttpError into an actionable HTTPException.

    The common setup failure is SERVICE_DISABLED (the API isn't enabled for the
    service-account's GCP project); surface a clear instruction with the
    activation URL instead of the raw error blob.
    """
    reason = ""
    activation_url = ""
    try:
        details = getattr(exc, "error_details", None) or []
        for d in details:
            if d.get("reason") == "SERVICE_DISABLED":
                reason = "SERVICE_DISABLED"
                activation_url = (d.get("metadata") or {}).get("activationUrl", "")
                break
    except Exception:
        pass

    if reason == "SERVICE_DISABLED":
        msg = (
            f"The {service} API is not enabled for the service-account's Google "
            f"Cloud project. Enable it, wait a few minutes, then retry."
        )
        if activation_url:
            msg += f" Enable it here: {activation_url}"
        return HTTPException(status_code=424, detail=msg)

    return HTTPException(status_code=502, detail=f"{service} error: {exc}")


@router.post("/sheets")
def export_to_sheets(data: dict = Body(...)):
    profile_id = data.get("profileId")
    start_date = data.get("startDate", "28daysAgo")
    end_date = data.get("endDate", "today")

    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    if ga4.demo_enabled():
        return {
            "ok": True,
            "demo": True,
            "tabs": [r.get("sheetTab") or r["key"] for r in report_defs.all_reports()],
            "message": "Demo mode: skipped the real Google Sheets write. Configure a "
            "service-account key and a shared spreadsheet to export for real.",
        }

    spreadsheet_id = profile.get("spreadsheetId")
    if not spreadsheet_id:
        raise HTTPException(
            status_code=400,
            detail="This site has no Google Sheet configured (set spreadsheetId).",
        )

    tabs: list[tuple[str, list[list]]] = []
    try:
        for rdef in report_defs.all_reports():
            if not datasource.applicable(rdef, profile):
                continue  # e.g. a MoEngage report on a profile with no MoEngage creds
            report = datasource.run_report(rdef, profile, start_date, end_date)
            tab = rdef.get("sheetTab") or rdef.get("name") or rdef["key"]
            tabs.append((tab, sheets.report_to_values(report)))
    except datasource.DataSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"GA4 Data API error: {exc}")

    try:
        result = sheets.export(
            spreadsheet_id,
            tabs,
            date_note=f"{start_date} → {end_date}",
            project_id=profile.get("projectId") or None,
        )
    except HttpError as exc:
        raise _google_http_error("Google Sheets", exc)

    return {"ok": True, **result}


@router.post("/slides")
def export_to_slides(data: dict = Body(...)):
    """Build the branded Google Slides deck for a site's month-over-month report."""
    profile_id = data.get("profileId")
    cur = data.get("current") or {}
    prev = data.get("previous") or {}

    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    if ga4.demo_enabled():
        return {
            "ok": True, "demo": True,
            "message": "Demo mode: skipped the real Google Slides build. Configure a "
            "service-account key and share a Slides deck with it to export for real.",
        }

    slides_id = profile.get("slidesId")
    if not slides_id:
        raise HTTPException(status_code=400,
                            detail="This site has no Google Slides deck configured (set slidesId).")

    current = {"start": cur.get("start"), "end": cur.get("end"), "label": cur.get("label", "This period")}
    previous = {"start": prev.get("start"), "end": prev.get("end"), "label": prev.get("label", "Previous period")}

    sections: list[dict] = []
    try:
        for rdef in report_defs.all_reports():
            if not datasource.applicable(rdef, profile):
                continue  # e.g. a MoEngage report on a profile with no MoEngage creds
            report = datasource.run_comparison(rdef, profile, current, previous)
            ins = insights_mod.generate(report)
            sections.append({"name": rdef.get("name", rdef["key"]),
                             "report": report, "insights": ins["insights"]})
    except datasource.DataSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail=f"GA4 Data API error: {exc}")

    try:
        result = slides.build_deck(
            slides_id,
            profile.get("name", "Site"),
            sections,
            project_id=profile.get("projectId") or None,
        )
    except HttpError as exc:
        raise _google_http_error("Google Slides", exc)

    return {"ok": True, **result}
