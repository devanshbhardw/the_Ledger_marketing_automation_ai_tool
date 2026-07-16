"""Ad-hoc Search Console querying: dynamic Search Analytics reports.

Mirrors ga4_query.py for agentic callers (the /ask tool loop): run_report runs
whatever query/page/country/device/date breakdown the model asks for and returns
Search Console's own error text on a bad request so the model can retry instead
of crashing.

Search Console has no numeric propertyId like GA4 — a site is identified by its
URL (e.g. "https://example.com/" or "sc-domain:example.com"), read from the
profile's searchConsoleSiteUrl. Every response carries all four metrics
(clicks, impressions, ctr, position), so there is no metric selection.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from . import ga4

log = logging.getLogger("ttk.search_console_query")

QUERY_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"

# Search Console rejects any other dimension name.
VALID_DIMENSIONS = {"query", "page", "country", "device", "date"}
# Returned on every row regardless of the request — no selection needed.
METRICS = ["clicks", "impressions", "ctr", "position"]


def _build_filter(dimension_filter: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """{"dimension": ..., "value": ..., "match": "equals"|"contains"} -> groups."""
    if not dimension_filter:
        return None
    match = (dimension_filter.get("match") or "equals").lower()
    operator = "contains" if match == "contains" else "equals"
    return [
        {
            "filters": [
                {
                    "dimension": dimension_filter["dimension"],
                    "operator": operator,
                    "expression": str(dimension_filter.get("value", "")),
                }
            ]
        }
    ]


def run_report(
    profile: dict[str, Any],
    dimensions: list[str],
    start_date: str,
    end_date: str,
    dimension_filter: dict[str, Any] | None = None,
    limit: int = 50,
    site_url: str | None = None,
) -> dict[str, Any]:
    """Run a Search Analytics query; on an API error return {"error": ...}.

    site_url overrides the profile's searchConsoleSiteUrl (Search Console keys
    sites by URL, not by a numeric id). Invalid dimensions are an expected
    outcome for an agentic caller, so the API's error text is returned (not
    raised) for the model to read and retry.
    """
    site = str(site_url or profile.get("searchConsoleSiteUrl") or "").strip()
    if not site:
        return {"error": "profile has no searchConsoleSiteUrl"}

    bad = [d for d in dimensions if d not in VALID_DIMENSIONS]
    if bad:
        return {
            "error": f"invalid dimension(s) {bad}; valid: {sorted(VALID_DIMENSIONS)}"
        }

    body: dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": max(1, min(int(limit), 25000)),
    }
    groups = _build_filter(dimension_filter)
    if groups:
        body["dimensionFilterGroups"] = groups

    url = QUERY_URL.format(site=quote(site, safe=""))
    session = AuthorizedSession(ga4.get_credentials_for_profile(profile))
    try:
        resp = session.post(url, json=body, timeout=60)
        if resp.status_code != 200:
            log.info("search analytics query failed for %s: %s", site, resp.text)
            return {"error": resp.text}
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — surface network/parse errors to the caller
        log.info("search analytics query failed for %s: %s", site, exc)
        return {"error": str(exc)}

    rows: list[dict[str, Any]] = []
    for row in payload.get("rows", []):
        record: dict[str, Any] = {}
        for name, key in zip(dimensions, row.get("keys", [])):
            record[name] = key
        for m in METRICS:
            record[m] = ga4._num(row.get(m, 0))
        rows.append(record)

    return {
        "dimensions": dimensions,
        "metrics": METRICS,
        "rows": rows,
        "rowCount": len(rows),
    }
