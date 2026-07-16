"""Ad-hoc Merchant Center querying: dynamic product-performance reports.

Mirrors ga4_query.py for agentic callers (the /ask tool loop): run_report builds
a simple SQL-like query from the requested fields against the
ProductPerformanceView and runs it through the Content API's Reports service
(accounts.reports.search), returning the API's own error text on a bad query so
the model can retry instead of crashing.

Scoped to the profile's merchantCenterId.
"""
from __future__ import annotations

import logging
from typing import Any

from google.auth.transport.requests import AuthorizedSession

from . import ga4

log = logging.getLogger("ttk.merchant_center_query")

SEARCH_URL = "https://shoppingcontent.googleapis.com/content/v2.1/{mid}/reports/search"
REPORT_VIEW = "ProductPerformanceView"


def _build_query(
    select_fields: list[str],
    start_date: str,
    end_date: str,
    dimension_filter: dict[str, Any] | None,
    limit: int,
) -> str:
    """Assemble the Reports query language string from the requested fields."""
    select = ", ".join(select_fields)
    where = [f"segments.date BETWEEN '{start_date}' AND '{end_date}'"]
    if dimension_filter:
        field = dimension_filter["dimension"]
        value = str(dimension_filter.get("value", "")).replace("'", "\\'")
        match = (dimension_filter.get("match") or "equals").lower()
        # The Reports query language uses = for exact and LIKE for substring.
        if match == "contains":
            where.append(f"{field} LIKE '%{value}%'")
        else:
            where.append(f"{field} = '{value}'")
    return (
        f"SELECT {select} FROM {REPORT_VIEW} "
        f"WHERE {' AND '.join(where)} "
        f"LIMIT {max(1, min(int(limit), 1000))}"
    )


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten Reports' nested result groups (segments/metrics/...) to dotted keys."""
    flat: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else key
            flat.update(_flatten(value, child))
    else:
        flat[prefix] = ga4._num(obj) if isinstance(obj, str) else obj
    return flat


def run_report(
    profile: dict[str, Any],
    select_fields: list[str],
    start_date: str,
    end_date: str,
    dimension_filter: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run a ProductPerformanceView report; on an API error return {"error": ...}.

    Invalid field combinations are an expected outcome for an agentic caller, so
    the API's error text is returned (not raised) for the model to read and retry.
    """
    mid = str(profile.get("merchantCenterId") or "").strip()
    if not mid:
        return {"error": "profile has no merchantCenterId"}
    if not select_fields:
        return {"error": "at least one select field is required"}

    query = _build_query(select_fields, start_date, end_date, dimension_filter, limit)
    url = SEARCH_URL.format(mid=mid)
    session = AuthorizedSession(ga4.get_credentials_for_profile(profile))
    try:
        resp = session.post(url, json={"query": query}, timeout=60)
        if resp.status_code != 200:
            log.info("merchant report failed for %s: %s", mid, resp.text)
            return {"error": resp.text}
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — surface network/parse errors to the caller
        log.info("merchant report failed for %s: %s", mid, exc)
        return {"error": str(exc)}

    rows = [_flatten(result) for result in payload.get("results", [])]
    return {
        "select": select_fields,
        "query": query,
        "rows": rows,
        "rowCount": len(rows),
    }
