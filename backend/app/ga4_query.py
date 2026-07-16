"""Ad-hoc GA4 querying: property metadata + dynamic reports.

Unlike ga4.py's config-driven report engine, these helpers take arbitrary
dimension/metric names at call time. They exist for agentic callers (the /ask
tool loop): get_metadata tells the model what fields this property supports,
run_dynamic_report runs whatever it asks for and returns GA4's own error text
on an invalid combination so the model can retry instead of crashing.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    GetMetadataRequest,
    Metric,
    MetricAggregation,
    RunReportRequest,
)
from google.api_core.exceptions import GoogleAPIError

from . import ga4

log = logging.getLogger("ttk.ga4_query")

METADATA_TTL_SECONDS = 3600

# propertyId -> (fetched_at, metadata dict). Metadata rarely changes, and an
# agent may ask for it several times per session — in-process cache is enough.
_metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def get_metadata(profile: dict[str, Any]) -> dict[str, Any]:
    """Available dimensions/metrics for this property (standard + custom).

    Returns {"dimensions": [{"apiName", "displayName"}, ...],
             "metrics":    [{"apiName", "displayName"}, ...]}
    """
    property_id = str(profile.get("propertyId") or "").strip()
    if not property_id:
        raise ValueError("profile has no propertyId")

    cached = _metadata_cache.get(property_id)
    if cached and time.time() - cached[0] < METADATA_TTL_SECONDS:
        return cached[1]

    client = BetaAnalyticsDataClient(
        credentials=ga4.get_credentials_for_profile(profile)
    )
    md = client.get_metadata(
        GetMetadataRequest(name=f"properties/{property_id}/metadata")
    )
    result = {
        "dimensions": [
            {"apiName": d.api_name, "displayName": d.ui_name} for d in md.dimensions
        ],
        "metrics": [
            {"apiName": m.api_name, "displayName": m.ui_name} for m in md.metrics
        ],
    }
    _metadata_cache[property_id] = (time.time(), result)
    return result


def _build_filter(dimension_filter: dict[str, Any] | None) -> FilterExpression | None:
    """{"dimension": ..., "value": ..., "match": "equals"|"contains"} -> filter."""
    if not dimension_filter:
        return None
    match = (dimension_filter.get("match") or "equals").lower()
    match_type = (
        Filter.StringFilter.MatchType.CONTAINS
        if match == "contains"
        else Filter.StringFilter.MatchType.EXACT
    )
    return FilterExpression(
        filter=Filter(
            field_name=dimension_filter["dimension"],
            string_filter=Filter.StringFilter(
                value=str(dimension_filter.get("value", "")),
                match_type=match_type,
                case_sensitive=False,
            ),
        )
    )


def run_dynamic_report(
    profile: dict[str, Any],
    dimensions: list[str],
    metrics: list[str],
    start_date: str,
    end_date: str,
    dimension_filter: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run an arbitrary GA4 report; on a GA4 API error return {"error": ...}.

    GA4 enforces dimension/metric compatibility rules, so invalid combinations
    are an expected outcome — the error text is returned (not raised) so an
    agent can read it and retry with different fields.
    """
    property_id = str(profile.get("propertyId") or "").strip()
    if not property_id:
        return {"error": "profile has no propertyId"}
    if not metrics:
        return {"error": "at least one metric is required"}

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        metric_aggregations=[MetricAggregation.TOTAL],
        dimension_filter=_build_filter(dimension_filter),
        limit=max(1, min(int(limit), 250)),
    )

    client = BetaAnalyticsDataClient(
        credentials=ga4.get_credentials_for_profile(profile)
    )
    try:
        response = client.run_report(request)
    except GoogleAPIError as exc:
        log.info("dynamic report failed for %s: %s", property_id, exc)
        return {"error": str(exc)}

    rows: list[dict[str, Any]] = []
    for row in response.rows:
        record: dict[str, Any] = {}
        for name, cell in zip(dimensions, row.dimension_values):
            record[name] = cell.value
        for name, cell in zip(metrics, row.metric_values):
            record[name] = ga4._num(cell.value)
        rows.append(record)

    totals: dict[str, Any] = {}
    if response.totals:
        for name, cell in zip(metrics, response.totals[0].metric_values):
            totals[name] = ga4._num(cell.value)

    return {
        "dimensions": dimensions,
        "metrics": metrics,
        "rows": rows,
        "totals": totals,
        "rowCount": response.row_count,
    }
