"""GA4 Data API + Admin API access.

Authentication uses a single service-account key (Application Default
Credentials style). The service-account email must be granted access on the GA4
property. No per-user OAuth is involved.
"""
from __future__ import annotations

import os
import random
from datetime import date
from functools import lru_cache
from typing import Any

from google.analytics.admin import AnalyticsAdminServiceClient
from google.api_core.exceptions import GoogleAPIError
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    MetricAggregation,
    OrderBy,
    RunReportRequest,
)
from google.auth.credentials import Credentials as BaseCredentials
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials

from . import connections, shape
from .config import settings

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",   # write reports to Google Sheets
    "https://www.googleapis.com/auth/presentations",  # build the Google Slides deck
]


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
# SERVICE_ACCOUNT_FILE may list several key files (comma-separated), one per
# GCP project / client. Each key is indexed by the project_id embedded in its
# JSON; a profile's `projectId` field selects which key serves that site.
def _key_paths() -> list[str]:
    raw = settings.service_account_file or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )
    return [p.strip() for p in raw.split(",") if p.strip()]


@lru_cache(maxsize=1)
def _credentials_by_project() -> dict[str, service_account.Credentials]:
    paths = _key_paths()
    if not paths:
        raise RuntimeError(
            "No service-account key configured. Set SERVICE_ACCOUNT_FILE or "
            "GOOGLE_APPLICATION_CREDENTIALS to the JSON key path(s)."
        )
    index: dict[str, service_account.Credentials] = {}
    for path in paths:
        creds = service_account.Credentials.from_service_account_file(
            path, scopes=SCOPES
        )
        if settings.quota_project_id:
            creds = creds.with_quota_project(settings.quota_project_id)
        index[creds.project_id] = creds
        # First key listed is the default (used when a profile has no projectId).
        index.setdefault("", creds)
    return index


def get_credentials(project_id: str | None = None) -> service_account.Credentials:
    """Return credentials for a GCP project (or the default/first key)."""
    index = _credentials_by_project()
    creds = index.get(project_id or "")
    if creds is None:
        raise RuntimeError(
            f"No service-account key configured for GCP project '{project_id}'. "
            f"Known projects: {sorted(k for k in index if k)}. Add its key file "
            "to SERVICE_ACCOUNT_FILE (comma-separated) in backend/.env."
        )
    return creds


def get_credentials_for_profile(profile: dict[str, Any] | None) -> BaseCredentials:
    """Credentials for one profile: its OAuth connection if it has one, else the
    service-account key selected by its projectId."""
    profile = profile or {}
    connection_id = (profile.get("connectionId") or "").strip()
    if connection_id:
        # connections.get_valid_access_token already refreshed if expired; the
        # refresh token + client id/secret let google-auth renew mid-request too.
        return UserCredentials(
            token=connections.get_valid_access_token(connection_id),
            refresh_token=connections.get_refresh_token(connection_id) or None,
            token_uri=connections.GOOGLE_TOKEN_URL,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            scopes=SCOPES,
        )
    return get_credentials(profile.get("projectId") or None)


# --------------------------------------------------------------------------- #
# Admin API — list properties the service account can access
# --------------------------------------------------------------------------- #
def list_properties() -> list[dict[str, Any]]:
    """List GA4 properties visible to ANY configured service account (deduped).

    A key whose project has the Admin API disabled (or no GA4 access yet) is
    skipped so one misconfigured project doesn't break listing for the rest.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for project_id, creds in _credentials_by_project().items():
        if not project_id:
            continue  # "" is the default alias of the first key
        client = AnalyticsAdminServiceClient(credentials=creds)
        try:
            summaries = list(client.list_account_summaries())
        except GoogleAPIError:
            continue
        for acct in summaries:
            for prop in acct.property_summaries:
                # property_summary.property is like "properties/123456789"
                pid = prop.property.split("/")[-1]
                if pid in seen:
                    continue
                seen.add(pid)
                out.append(
                    {
                        "account": acct.display_name,
                        "propertyId": pid,
                        "displayName": prop.display_name,
                        "projectId": project_id,
                    }
                )
    return out


# --------------------------------------------------------------------------- #
# Report engine (config-driven)
# --------------------------------------------------------------------------- #
# A report definition is a plain dict (see report_defs.py / report_defs.json):
#   {
#     "key": "traffic-acquisition",
#     "name": "Traffic Acquisition",
#     "dimensions": ["{channelGroup}", "sessionSourceMedium"],  # tokens allowed
#     "metrics": ["sessions", "totalUsers"],
#     "orderBy": "sessions",     # metric name to sort desc by (optional)
#     "limit": 100,
#   }
#
# The token "{channelGroup}" is replaced per-site with the profile's custom
# channel-group dimension (or the standard sessionDefaultChannelGroup).

CHANNEL_GROUP_TOKEN = "{channelGroup}"
DEFAULT_CHANNEL_GROUP = "sessionDefaultChannelGroup"


def _resolve_dimension(name: str, channel_group_dimension: str | None) -> str:
    if name == CHANNEL_GROUP_TOKEN:
        return channel_group_dimension or DEFAULT_CHANNEL_GROUP
    return name


def _clamp_date(value: str) -> str:
    """Clamp an absolute YYYY-MM-DD date to today.

    GA4's currency-exchange table holds no future rates, so any report with a
    revenue metric (converted to the property currency) fails with
    "Future currency exchange rate not exist" when the date range extends past
    today. Relative expressions ("today", "yesterday", "28daysAgo") are passed
    through untouched — GA4 resolves those safely on its side.
    """
    try:
        d = date.fromisoformat(value)
    except (ValueError, TypeError):
        return value
    today = date.today()
    return today.isoformat() if d > today else value


# --------------------------------------------------------------------------- #
# Demo mode — synthetic data so the UI works with no GCP setup
# --------------------------------------------------------------------------- #
def demo_enabled() -> bool:
    if settings.demo_mode:
        return True
    key_path = settings.service_account_file or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )
    return not key_path

_DEMO_VALUES = {
    "{channelGroup}": ["Organic Search", "Direct", "Paid Search", "Referral", "Organic Social", "Email"],
    "sessionDefaultChannelGroup": ["Organic Search", "Direct", "Paid Search", "Referral", "Organic Social", "Email"],
    "sessionSourceMedium": ["google / organic", "(direct) / (none)", "google / cpc", "bing / organic", "newsletter / email"],
    "pagePath": ["/", "/products", "/pricing", "/about", "/blog", "/contact"],
    "pageTitle": ["Home", "Products", "Pricing", "About", "Blog", "Contact"],
    "eventName": ["page_view", "session_start", "scroll", "click", "add_to_cart", "purchase"],
    "country": ["United States", "India", "United Kingdom", "Germany", "Canada", "Australia"],
    "deviceCategory": ["desktop", "mobile", "tablet"],
    "browser": ["Chrome", "Safari", "Edge", "Firefox"],
    "newVsReturning": ["new", "returning"],
}


def _demo_metric(name: str, scale: float, rng: random.Random) -> float | int:
    low = name.lower()
    if "rate" in low:
        return round(rng.uniform(0.25, 0.85), 4)
    if "revenue" in low:
        return round(scale * rng.uniform(2.0, 12.0), 2)
    if "duration" in low:
        return int(scale * rng.uniform(20, 90))
    if "persession" in low or "per session" in low:
        return round(rng.uniform(1.5, 6.0), 2)
    return int(scale * rng.uniform(5, 40))


def _demo_report(
    report_def: dict[str, Any],
    property_id: str,
    dim_names: list[str],
    met_names: list[str],
    seed: str = "",
) -> dict[str, Any]:
    # Deterministic per seed so repeated loads look stable, but different date
    # ranges (different seed) yield different numbers -> realistic MoM movement.
    rng = random.Random(seed or f"{report_def.get('key')}:{property_id}")
    pools = [(_DEMO_VALUES.get(d) or [f"{d} {i+1}" for i in range(6)]) for d in dim_names]
    n = min(int(report_def.get("limit", 100)), 12)

    rows: list[dict[str, Any]] = []
    for i in range(n):
        scale = float(n - i)  # descending so orderBy looks sorted
        record: dict[str, Any] = {}
        for d, pool in zip(dim_names, pools):
            record[d] = pool[i % len(pool)]
        for m in met_names:
            record[m] = _demo_metric(m, scale, rng)
        rows.append(record)

    # Reflect the configured sort so the demo looks like the real report.
    order_field = report_def.get("orderBy")
    if order_field and rows and order_field in rows[0]:
        rows.sort(
            key=lambda r: r[order_field],
            reverse=bool(report_def.get("orderDesc", True)),
        )

    totals = {
        m: round(sum(float(r[m]) for r in rows), 2) if any("." in str(r[m]) for r in rows)
        else sum(int(r[m]) for r in rows)
        for m in met_names
    }
    return {
        "dimensions": dim_names,
        "metrics": met_names,
        "rows": rows,
        "totals": totals,
        "rowCount": len(rows),
        "demo": True,
    }


def _add_metric(a: Any, b: Any) -> Any:
    """Sum two metric values, preserving int-ness; fall back to first non-empty."""
    try:
        s = float(a) + float(b)
        return int(s) if s.is_integer() else round(s, 4)
    except (ValueError, TypeError):
        return a or b


def _strip_query(data: dict[str, Any], report_def: dict[str, Any]) -> dict[str, Any]:
    """Drop the query string (and fragment) from dimension values and merge rows
    that collapse to the same value, summing metrics.

    GA4 has no native query-string-free landing-page dimension, so reports pull
    `landingPagePlusQueryString` and set `stripQuery` to parse the path out here.
    `stripQuery: true` cleans every dimension; a list names specific dimensions.
    Runs before `_apply_computed` so ratio columns are computed on merged totals.
    """
    spec = report_def.get("stripQuery")
    if not spec:
        return data
    dims: list[str] = data["dimensions"]
    mets: list[str] = data["metrics"]
    clean_dims = spec if isinstance(spec, list) else dims

    def clean(v: Any) -> Any:
        if isinstance(v, str):
            return v.split("?", 1)[0].split("#", 1)[0]
        return v

    merged: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for row in data["rows"]:
        for d in clean_dims:
            if d in row:
                row[d] = clean(row[d])
        k = tuple(row.get(d) for d in dims)
        if k not in merged:
            merged[k] = {d: row.get(d) for d in dims} | {m: 0 for m in mets}
            order.append(k)
        for m in mets:
            merged[k][m] = _add_metric(merged[k][m], row.get(m, 0))

    rows = [merged[k] for k in order]
    order_field = report_def.get("orderBy")
    if order_field in mets:
        rows.sort(key=lambda r: r.get(order_field, 0), reverse=bool(report_def.get("orderDesc", True)))
    data["rows"] = rows
    data["rowCount"] = len(rows)
    return data


def _apply_computed(data: dict[str, Any], report_def: dict[str, Any]) -> dict[str, Any]:
    """Add derived columns (e.g. conversion rate = transactions / sessions)."""
    computed = report_def.get("computed") or []
    for c in computed:
        key, num, den = c["key"], c["numerator"], c["denominator"]
        pct = bool(c.get("percent"))

        def ratio(n: Any, d: Any) -> float:
            try:
                n, d = float(n), float(d)
                return round((n / d) * (100 if pct else 1), 4) if d else 0.0
            except (TypeError, ValueError):
                return 0.0

        for row in data["rows"]:
            row[key] = ratio(row.get(num, 0), row.get(den, 0))
        data["totals"][key] = ratio(data["totals"].get(num, 0), data["totals"].get(den, 0))
        if key not in data["metrics"]:
            data["metrics"].append(key)
    return data


def _dimension_filter(report_def: dict[str, Any], channel_group_dimension: str | None):
    """Build an exact-match dimension filter from report_def['filter'], if present."""
    flt = report_def.get("filter")
    if not flt:
        return None
    field = _resolve_dimension(flt["dimension"], channel_group_dimension)
    return FilterExpression(
        filter=Filter(
            field_name=field,
            string_filter=Filter.StringFilter(
                value=flt["value"], match_type=Filter.StringFilter.MatchType.EXACT
            ),
        )
    )


def run_report(
    report_def: dict[str, Any],
    property_id: str,
    start_date: str,
    end_date: str,
    channel_group_dimension: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Original (token) dimension names stay the row keys so the frontend columns
    # are stable across sites; the query uses the resolved API names.
    dim_names: list[str] = list(report_def.get("dimensions", []))
    met_names: list[str] = list(report_def.get("metrics", []))

    if demo_enabled():
        seed = f"{report_def.get('key')}:{property_id}:{start_date}:{end_date}"
        return _apply_computed(
            _strip_query(_demo_report(report_def, property_id, dim_names, met_names, seed), report_def),
            report_def,
        )

    resolved_dims = [_resolve_dimension(d, channel_group_dimension) for d in dim_names]

    order_bys = []
    order_field = report_def.get("orderBy")
    order_desc = bool(report_def.get("orderDesc", True))
    if order_field:
        if order_field in met_names:
            order_bys.append(
                OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name=order_field),
                    desc=order_desc,
                )
            )
        else:
            # Order by a dimension (resolve the channel-group token if used).
            order_bys.append(
                OrderBy(
                    dimension=OrderBy.DimensionOrderBy(
                        dimension_name=_resolve_dimension(
                            order_field, channel_group_dimension
                        )
                    ),
                    desc=order_desc,
                )
            )

    # Never query past today: GA4 revenue metrics are currency-converted and its
    # exchange-rate table has no future rates (see _clamp_date).
    start_date, end_date = _clamp_date(start_date), _clamp_date(end_date)

    client = BetaAnalyticsDataClient(credentials=get_credentials_for_profile(profile))
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=d) for d in resolved_dims],
        metrics=[Metric(name=m) for m in met_names],
        metric_aggregations=[MetricAggregation.TOTAL],
        dimension_filter=_dimension_filter(report_def, channel_group_dimension),
        order_bys=order_bys,
        limit=int(report_def.get("limit", 100)),
    )
    response = client.run_report(request)
    return _apply_computed(
        _strip_query(_normalize(response, dim_names, met_names), report_def), report_def
    )


def _normalize(
    response: Any, dim_names: list[str], met_names: list[str]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in response.rows:
        record: dict[str, Any] = {}
        for name, cell in zip(dim_names, row.dimension_values):
            record[name] = cell.value
        for name, cell in zip(met_names, row.metric_values):
            record[name] = _num(cell.value)
        rows.append(record)

    totals: dict[str, Any] = {}
    if response.totals:
        for name, cell in zip(met_names, response.totals[0].metric_values):
            totals[name] = _num(cell.value)

    return {
        "dimensions": dim_names,
        "metrics": met_names,
        "rows": rows,
        "totals": totals,
        "rowCount": response.row_count,
    }


def _num(value: str) -> float | int | str:
    try:
        f = float(value)
        return int(f) if f.is_integer() else round(f, 4)
    except (ValueError, TypeError):
        return value


# --------------------------------------------------------------------------- #
# Month-over-month comparison
# --------------------------------------------------------------------------- #
def run_comparison(
    report_def: dict[str, Any],
    property_id: str,
    current: dict[str, str],   # {"start","end","label"}
    previous: dict[str, str],
    channel_group_dimension: str | None = None,
    include_previous: bool = True,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the report for one or two periods and merge rows by dimension values.

    When include_previous is False, only the current period is fetched (single
    GA4 call) and the previous side is left empty.
    """
    dim_names: list[str] = list(report_def.get("dimensions", []))

    cur = run_report(
        report_def, property_id, current["start"], current["end"],
        channel_group_dimension, profile,
    )
    if include_previous:
        prev = run_report(
            report_def, property_id, previous["start"], previous["end"],
            channel_group_dimension, profile,
        )
    else:
        prev = {"rows": [], "totals": {}}
    return shape.merge_periods(
        report_def, dim_names, cur, prev, current, previous, include_previous
    )
