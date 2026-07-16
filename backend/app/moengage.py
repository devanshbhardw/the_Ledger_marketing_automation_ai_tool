"""MoEngage campaign-analytics data source.

Emits the SAME normalized report shape as ga4.py so the whole consumer layer
(sheets, slides, insights, frontend, comparison merge) works unchanged:
    {dimensions, metrics, rows[], totals, rowCount, demo?}

Model: one campaign = one row. The dimension is the campaign name (+ optional
campaign type); metrics are stats fields (sent, delivered, opens, clicks, ...).

Credentials are per-profile (entered in the UI, stored on the profile):
    moengageAppId       -> MOE-APPKEY header (workspace / app id)
    moengageApiKey      -> DATA API key (HTTP Basic password)
    moengageDataCenter  -> data-center number, e.g. "01" (host api-01.moengage.com)

NOTE: the live MoEngage request/response JSON is only partially confirmed (the
developer docs are auth-gated). All HTTP + field parsing is isolated in
`_request`, `_list_campaigns`, and `_parse_stats_row` so verified names are a
one-line fix. Until real credentials are wired and verified, demo mode returns
synthetic campaigns so the dashboard/exports work end-to-end.
"""
from __future__ import annotations

import base64
import random
from typing import Any

import httpx

from . import shape
from .config import settings
from .ga4 import _apply_computed, _num
from .shape import DataSourceError

# Synthetic dimension tokens this source understands as row keys.
CAMPAIGN_NAME = "campaignName"
CAMPAIGN_TYPE = "campaignType"

# Our metric name -> candidate field names in the MoEngage stats response. The
# first present key wins. Adjust the candidates once verified against a live
# workspace (Step 6 of the plan) — this is the single place field names live.
_METRIC_FIELDS: dict[str, tuple[str, ...]] = {
    "sent": ("sent", "sends", "total_sent"),
    "delivered": ("delivered", "delivery", "total_delivered"),
    "opens": ("opens", "opened", "unique_opens"),
    "clicks": ("clicks", "clicked", "unique_clicks"),
    "impressions": ("impressions", "impression"),
    "conversions": ("conversions", "conversion", "goal_conversions"),
    "bounces": ("bounces", "bounced", "hard_bounces"),
}

# Campaign delivery-type enum values we filter by. Flows/journeys may use a
# distinct value or endpoint — verify against the live API before trusting.
DELIVERY_ONE_TIME = "ONE_TIME"
DELIVERY_FLOW = "FLOW"

_HTTP_TIMEOUT = 30.0
_STATS_BATCH = 10  # campaign-stats accepts at most 10 campaign ids per call


# --------------------------------------------------------------------------- #
# Credentials / demo gating
# --------------------------------------------------------------------------- #
def _creds(profile: dict[str, Any]) -> tuple[str, str, str]:
    return (
        (profile.get("moengageAppId") or "").strip(),
        (profile.get("moengageApiKey") or "").strip(),
        (profile.get("moengageDataCenter") or "").strip(),
    )


def _has_creds(profile: dict[str, Any]) -> bool:
    app_id, api_key, dc = _creds(profile)
    return bool(app_id and api_key and dc)


def demo_enabled(profile: dict[str, Any]) -> bool:
    """Synthetic data when forced, or when this profile has no MoEngage creds."""
    return settings.demo_mode or not _has_creds(profile)


# --------------------------------------------------------------------------- #
# HTTP isolation layer
# --------------------------------------------------------------------------- #
def _base_url(dc: str) -> str:
    return f"https://api-{dc}.moengage.com"


def _headers(app_id: str, api_key: str) -> dict[str, str]:
    # HTTP Basic username is the app id, password is the DATA API key. If a live
    # workspace turns out to use a separate app-key as the username, add a
    # `moengageAppKey` profile field and swap it in here only.
    token = base64.b64encode(f"{app_id}:{api_key}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "MOE-APPKEY": app_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(
    profile: dict[str, Any],
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single MoEngage HTTP entrypoint. Maps transport/HTTP errors to
    DataSourceError with actionable, status-mapped messages."""
    app_id, api_key, dc = _creds(profile)
    url = f"{_base_url(dc)}{path}"
    try:
        resp = httpx.request(
            method, url, headers=_headers(app_id, api_key),
            json=json, params=params, timeout=_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise DataSourceError(f"MoEngage request failed: {exc}", status_code=502)

    if resp.status_code in (401, 403):
        raise DataSourceError(
            "MoEngage authentication failed — verify the profile's App ID, DATA "
            "API key, and data-center number.",
            status_code=502,
        )
    if resp.status_code == 429:
        raise DataSourceError(
            "MoEngage rate limit hit (max ~100 calls/min). Try again shortly.",
            status_code=503,
        )
    if resp.status_code >= 500:
        raise DataSourceError(f"MoEngage upstream error ({resp.status_code}).", status_code=502)
    if resp.status_code >= 400:
        raise DataSourceError(
            f"MoEngage request rejected ({resp.status_code}): {resp.text[:300]}",
            status_code=502,
        )
    try:
        return resp.json()
    except ValueError:
        raise DataSourceError("MoEngage returned a non-JSON response.", status_code=502)


def _list_campaigns(
    profile: dict[str, Any], start: str, end: str, campaign_types: list[str]
) -> list[dict[str, Any]]:
    """Enumerate campaigns of the given delivery types active in [start, end].
    Returns [{id, name, type}]. Parses only id / basic_details.name / delivery_type.
    """
    out: list[dict[str, Any]] = []
    offset, limit = 0, 100
    while True:
        body = {
            "filters": {"delivery_type": campaign_types, "date_range": {"start": start, "end": end}},
            "offset": offset,
            "limit": limit,
        }
        data = _request(profile, "POST", "/core-services/v1/campaigns/search", json=body)
        campaigns = data.get("campaigns") or data.get("data") or []
        for c in campaigns:
            basic = c.get("basic_details") or {}
            out.append(
                {
                    "id": c.get("id") or c.get("campaign_id"),
                    "name": basic.get("name") or c.get("name") or "(unnamed)",
                    "type": c.get("delivery_type") or c.get("type") or "",
                }
            )
        if len(campaigns) < limit:
            break
        offset += limit
    return [c for c in out if c["id"]]


def _parse_stats_row(raw: dict[str, Any], met_names: list[str]) -> dict[str, Any]:
    """Extract the requested metrics from one campaign's stats object, trying the
    candidate field names in _METRIC_FIELDS. Metrics may be nested under a
    `stats`/`metrics` object; check both the row and that nested object."""
    nested = raw.get("stats") or raw.get("metrics") or {}
    out: dict[str, Any] = {}
    for m in met_names:
        val = 0
        for field in _METRIC_FIELDS.get(m, (m,)):
            if field in raw:
                val = raw[field]
                break
            if field in nested:
                val = nested[field]
                break
        out[m] = _num(val) if not isinstance(val, str) else _num(val)
    return out


def _fetch_stats(
    profile: dict[str, Any], ids: list[str], start: str, end: str, metric_type: str
) -> dict[str, dict[str, Any]]:
    """Fetch stats for campaign ids in batches of <=10; return {id: raw_stats}."""
    result: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), _STATS_BATCH):
        chunk = ids[i : i + _STATS_BATCH]
        body = {
            "campaign_ids": chunk,
            "start_date": start,
            "end_date": end,
            "metric_type": metric_type,
        }
        data = _request(profile, "POST", "/core-services/v1/campaign-stats", json=body)
        rows = data.get("data") or data.get("stats") or data.get("campaigns") or []
        for row in rows:
            cid = row.get("campaign_id") or row.get("id")
            if cid:
                result[str(cid)] = row
    return result


# --------------------------------------------------------------------------- #
# Demo mode — synthetic campaigns
# --------------------------------------------------------------------------- #
_DEMO_ONE_TIME = [
    "Summer Sale Blast", "Diwali Offer Announcement", "Weekend Flash Sale",
    "New Arrivals Newsletter", "Clearance Reminder", "Festive Coupon Drop",
]
_DEMO_FLOWS = [
    "Welcome Flow", "Cart Abandonment", "Browse Abandonment",
    "Post-Purchase Thank You", "Win-Back Journey", "Price Drop Alert",
]


def _demo_report(
    report_def: dict[str, Any], dim_names: list[str], met_names: list[str], seed: str
) -> dict[str, Any]:
    rng = random.Random(seed or report_def.get("key"))
    types = report_def.get("campaignTypes", [DELIVERY_ONE_TIME])
    pool = _DEMO_FLOWS if DELIVERY_FLOW in types else _DEMO_ONE_TIME
    ctype = "Flow" if DELIVERY_FLOW in types else "One-time"
    n = min(int(report_def.get("limit", 50)), len(pool))

    rows: list[dict[str, Any]] = []
    for i in range(n):
        sent = rng.randint(2000, 60000)
        delivered = int(sent * rng.uniform(0.95, 0.99))
        opens = int(delivered * rng.uniform(0.2, 0.55))
        clicks = int(opens * rng.uniform(0.05, 0.25))
        conversions = int(clicks * rng.uniform(0.03, 0.2))
        pool_vals = {
            "sent": sent, "delivered": delivered, "opens": opens, "clicks": clicks,
            "impressions": delivered, "conversions": conversions,
            "bounces": sent - delivered,
        }
        record: dict[str, Any] = {}
        if CAMPAIGN_NAME in dim_names:
            record[CAMPAIGN_NAME] = pool[i]
        if CAMPAIGN_TYPE in dim_names:
            record[CAMPAIGN_TYPE] = ctype
        for m in met_names:
            record[m] = pool_vals.get(m, rng.randint(0, 100))
        rows.append(record)

    return _assemble(report_def, dim_names, met_names, rows, demo=True)


# --------------------------------------------------------------------------- #
# Assembly (shared by live + demo)
# --------------------------------------------------------------------------- #
def _assemble(
    report_def: dict[str, Any],
    dim_names: list[str],
    met_names: list[str],
    rows: list[dict[str, Any]],
    demo: bool,
) -> dict[str, Any]:
    """Sum totals, sort by orderBy, truncate to limit, apply computed columns."""
    order_field = report_def.get("orderBy")
    if order_field in met_names:
        rows.sort(
            key=lambda r: r.get(order_field, 0) or 0,
            reverse=bool(report_def.get("orderDesc", True)),
        )
    limit = int(report_def.get("limit", 50))
    rows = rows[:limit]

    totals = {m: 0 for m in met_names}
    for r in rows:
        for m in met_names:
            v = r.get(m, 0)
            if isinstance(v, (int, float)):
                totals[m] += v
    totals = {m: _num(v) for m, v in totals.items()}

    data = {
        "dimensions": dim_names,
        "metrics": list(met_names),
        "rows": rows,
        "totals": totals,
        "rowCount": len(rows),
        "demo": demo,
    }
    return _apply_computed(data, report_def)


# --------------------------------------------------------------------------- #
# Public entrypoints (parallel ga4.run_report / run_comparison)
# --------------------------------------------------------------------------- #
def run_report(
    report_def: dict[str, Any], profile: dict[str, Any], start_date: str, end_date: str
) -> dict[str, Any]:
    dim_names: list[str] = list(report_def.get("dimensions", [CAMPAIGN_NAME]))
    met_names: list[str] = list(report_def.get("metrics", []))
    campaign_types: list[str] = report_def.get("campaignTypes", [DELIVERY_ONE_TIME])
    metric_type: str = report_def.get("metricType", "TOTAL")

    if demo_enabled(profile):
        seed = f"{report_def.get('key')}:{profile.get('id')}:{start_date}:{end_date}"
        return _demo_report(report_def, dim_names, met_names, seed)

    campaigns = _list_campaigns(profile, start_date, end_date, campaign_types)
    ids = [str(c["id"]) for c in campaigns]
    stats = _fetch_stats(profile, ids, start_date, end_date, metric_type)

    rows: list[dict[str, Any]] = []
    for c in campaigns:
        raw = stats.get(str(c["id"]))
        if raw is None:
            continue
        record: dict[str, Any] = {}
        if CAMPAIGN_NAME in dim_names:
            record[CAMPAIGN_NAME] = c["name"]
        if CAMPAIGN_TYPE in dim_names:
            record[CAMPAIGN_TYPE] = c["type"]
        record.update(_parse_stats_row(raw, met_names))
        rows.append(record)

    return _assemble(report_def, dim_names, met_names, rows, demo=False)


def run_comparison(
    report_def: dict[str, Any],
    profile: dict[str, Any],
    current: dict[str, str],
    previous: dict[str, str],
    include_previous: bool = True,
) -> dict[str, Any]:
    dim_names: list[str] = list(report_def.get("dimensions", [CAMPAIGN_NAME]))
    cur = run_report(report_def, profile, current["start"], current["end"])
    if include_previous:
        prev = run_report(report_def, profile, previous["start"], previous["end"])
    else:
        prev = {"rows": [], "totals": {}}
    return shape.merge_periods(
        report_def, dim_names, cur, prev, current, previous, include_previous
    )
