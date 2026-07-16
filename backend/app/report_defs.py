"""The shared monthly-report template.

Every site runs the same set of reports (only the data differs). Definitions
live in report_defs.json next to the backend so they can be edited without
touching code; if the file is missing it is seeded with the defaults below.

Each report:
  key        stable id (used in URLs / cache keys)
  name       section heading shown in the UI
  source     data source: "ga4" (default) or "moengage"
  campaignTypes  MoEngage only: delivery types to include, e.g. ["ONE_TIME"], ["FLOW"]
  metricType     MoEngage only: "TOTAL" or "UNIQUE"
  dimensions GA4 dimension API names; the token "{channelGroup}" is replaced
             per-site with the profile's custom channel group (or the standard
             sessionDefaultChannelGroup)
  metrics    GA4 metric API names
  orderBy    metric name to sort rows by, descending (optional)
  limit      max rows
  sheetTab   Google Sheets tab name for this report
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

DEFS_PATH = Path(os.environ.get("REPORT_DEFS_FILE", "report_defs.json"))

# Sensible starting template — replace/extend once the exact monthly report
# specs (metrics, dimensions, rows) are provided.
DEFAULT_DEFS: list[dict[str, Any]] = [
    {
        "key": "traffic-acquisition",
        "name": "Traffic Acquisition",
        # channel grouping + source/medium
        "dimensions": ["{channelGroup}", "sessionSourceMedium"],
        # sessions, users, conversions, revenue
        "metrics": ["sessions", "totalUsers", "conversions", "totalRevenue"],
        "orderBy": "sessions",
        "orderDesc": True,  # biggest channels first (matches the monthly deck)
        "limit": 10,
        "sheetTab": "Traffic Acquisition",
    },
    # Ecommerce reports share this metric set: sessions, transactions, revenue,
    # and a computed conversion rate (transactions / sessions, as a %).
    {
        "key": "session-campaign",
        "name": "Session Campaign",
        "dimensions": ["sessionCampaignName"],
        "metrics": ["sessions", "transactions", "totalRevenue"],
        "computed": [{"key": "convRate", "numerator": "transactions", "denominator": "sessions", "percent": True}],
        "orderBy": "sessions",
        "orderDesc": True,
        "limit": 25,
        "sheetTab": "Session Campaign",
    },
    {
        "key": "landing-page-overall",
        "name": "Landing Page (Overall)",
        "dimensions": ["landingPagePlusQueryString"],
        "stripQuery": True,
        "metrics": ["sessions", "transactions", "totalRevenue"],
        "computed": [{"key": "convRate", "numerator": "transactions", "denominator": "sessions", "percent": True}],
        "orderBy": "sessions",
        "orderDesc": True,
        "limit": 25,
        "sheetTab": "Landing Page",
    },
    {
        "key": "landing-page-meta",
        "name": "Landing Page: Meta Paid",
        "dimensions": ["landingPagePlusQueryString"],
        "stripQuery": True,
        "metrics": ["sessions", "transactions", "totalRevenue"],
        "computed": [{"key": "convRate", "numerator": "transactions", "denominator": "sessions", "percent": True}],
        "filter": {"dimension": "{channelGroup}", "value": "Meta Paid"},
        "orderBy": "sessions",
        "orderDesc": True,
        "limit": 25,
        "sheetTab": "Landing Meta Paid",
    },
    {
        "key": "landing-page-google",
        "name": "Landing Page: Google Paid",
        "dimensions": ["landingPagePlusQueryString"],
        "stripQuery": True,
        "metrics": ["sessions", "transactions", "totalRevenue"],
        "computed": [{"key": "convRate", "numerator": "transactions", "denominator": "sessions", "percent": True}],
        "filter": {"dimension": "{channelGroup}", "value": "Google Paid"},
        "orderBy": "sessions",
        "orderDesc": True,
        "limit": 25,
        "sheetTab": "Landing Google Paid",
    },
    {
        "key": "device-category",
        "name": "Device Category",
        "dimensions": ["deviceCategory"],
        "metrics": ["sessions", "transactions", "totalRevenue"],
        "computed": [{"key": "convRate", "numerator": "transactions", "denominator": "sessions", "percent": True}],
        "orderBy": "sessions",
        "orderDesc": True,
        "limit": 10,
        "sheetTab": "Device Category",
    },
    {
        "key": "product-enrichment",
        "name": "Product Analysis",
        # item name + channel grouping (per-site custom group via the token),
        # matching GA4's Item name × Session channel grouping exploration.
        "dimensions": ["itemName", "{channelGroup}"],
        "metrics": [
            "itemsViewed",
            "itemsAddedToCart",
            "itemsCheckedOut",
            "itemsPurchased",
            "itemRevenue",
        ],
        "orderBy": "itemsViewed",
        "orderDesc": True,
        "limit": 500,
        "sheetTab": "Product Analysis",
    },
    {
        "key": "moengage-one-time",
        "name": "MoEngage One-Time",
        "source": "moengage",
        "campaignTypes": ["ONE_TIME"],
        "metricType": "TOTAL",
        "dimensions": ["campaignName"],
        "metrics": ["sent", "delivered", "opens", "clicks", "conversions"],
        # Computed percent columns are named with a "Rate" substring so the
        # frontend's fmtMetric renders them as % without any change.
        "computed": [
            {"key": "clickRate", "numerator": "clicks", "denominator": "delivered", "percent": True},
            {"key": "openRate", "numerator": "opens", "denominator": "delivered", "percent": True},
        ],
        "orderBy": "sent",
        "orderDesc": True,
        "limit": 50,
        "sheetTab": "MoEngage One-Time",
    },
    {
        "key": "moengage-flows",
        "name": "MoEngage Flows",
        "source": "moengage",
        "campaignTypes": ["FLOW"],
        "metricType": "TOTAL",
        "dimensions": ["campaignName"],
        "metrics": ["sent", "delivered", "opens", "clicks", "conversions"],
        "computed": [
            {"key": "clickRate", "numerator": "clicks", "denominator": "delivered", "percent": True},
            {"key": "openRate", "numerator": "opens", "denominator": "delivered", "percent": True},
        ],
        "orderBy": "sent",
        "orderDesc": True,
        "limit": 50,
        "sheetTab": "MoEngage Flows",
    },
]


def _load() -> list[dict[str, Any]]:
    if DEFS_PATH.exists():
        try:
            data = json.loads(DEFS_PATH.read_text())
            if isinstance(data, dict):
                data = data.get("reports", [])
            if isinstance(data, list) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    # Seed the file with defaults on first run.
    save(DEFAULT_DEFS)
    return list(DEFAULT_DEFS)


def save(defs: list[dict[str, Any]]) -> None:
    DEFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFS_PATH.write_text(json.dumps({"reports": defs}, indent=2))


def all_reports() -> list[dict[str, Any]]:
    return _load()


def get(key: str) -> dict[str, Any] | None:
    return next((r for r in _load() if r.get("key") == key), None)


# Fields that change the shape/content of a report's data. Folded into the cache
# key so editing a definition (e.g. adding a dimension) invalidates stale entries
# instead of serving pre-change data.
_SIG_FIELDS = ("source", "dimensions", "metrics", "filter", "computed", "orderBy", "orderDesc", "limit", "stripQuery", "campaignTypes", "metricType")


def signature(rdef: dict[str, Any]) -> str:
    payload = {k: rdef.get(k) for k in _SIG_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
