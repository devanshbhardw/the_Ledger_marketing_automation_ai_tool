"""Data-source dispatch: route a report to GA4 or MoEngage by its `source` field.

Every report definition has an implicit `source: "ga4"` (default) or
`source: "moengage"`. The routers/scheduler/export call THIS module instead of
`ga4` directly; it forwards to the right backend, passing the whole profile so
each source unpacks the fields it needs. Both backends return the identical
normalized/comparison shapes, so everything downstream is source-agnostic.
"""
from __future__ import annotations

from typing import Any

from . import ga4, moengage
from .shape import DataSourceError  # re-exported for the router seams

__all__ = ["run_report", "run_comparison", "demo_enabled", "applicable", "DataSourceError"]


def _source(report_def: dict[str, Any]) -> str:
    return (report_def.get("source") or "ga4").lower()


def applicable(report_def: dict[str, Any], profile: dict[str, Any]) -> bool:
    """Whether this report can run for this profile (has the required creds/ids).
    Used by the scheduler/export loops to skip reports a profile can't serve."""
    if _source(report_def) == "moengage":
        return bool(profile.get("moengageAppId"))
    return bool(profile.get("propertyId"))


def demo_enabled(report_def: dict[str, Any], profile: dict[str, Any]) -> bool:
    if _source(report_def) == "moengage":
        return moengage.demo_enabled(profile)
    return ga4.demo_enabled()


def run_report(
    report_def: dict[str, Any], profile: dict[str, Any], start: str, end: str
) -> dict[str, Any]:
    if _source(report_def) == "moengage":
        return moengage.run_report(report_def, profile, start, end)
    return ga4.run_report(
        report_def,
        profile["propertyId"],
        start,
        end,
        channel_group_dimension=profile.get("channelGroupDim") or None,
        profile=profile,
    )


def run_comparison(
    report_def: dict[str, Any],
    profile: dict[str, Any],
    current: dict[str, str],
    previous: dict[str, str],
    include_previous: bool = True,
) -> dict[str, Any]:
    if _source(report_def) == "moengage":
        return moengage.run_comparison(
            report_def, profile, current, previous, include_previous=include_previous
        )
    return ga4.run_comparison(
        report_def,
        profile["propertyId"],
        current,
        previous,
        channel_group_dimension=profile.get("channelGroupDim") or None,
        include_previous=include_previous,
        profile=profile,
    )
