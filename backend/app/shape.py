"""Source-neutral helpers for the normalized report shape.

Both ga4.py and moengage.py return the same normalized report
(`{dimensions, metrics, rows[], totals, rowCount, demo?}`); this module merges a
current + previous period pair into the comparison shape consumed by the frontend,
insights, and the Slides export. Kept dependency-free so any data source can import
it without a circular import.
"""
from __future__ import annotations

from typing import Any


class DataSourceError(Exception):
    """A data-source (GA4/MoEngage) failure carrying the HTTP status + message to
    surface to the client. Raised by source modules, translated to HTTPException
    at the router seams."""

    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def merge_periods(
    report_def: dict[str, Any],
    dim_names: list[str],
    cur: dict[str, Any],
    prev: dict[str, Any],
    current: dict[str, str],
    previous: dict[str, str],
    include_previous: bool,
) -> dict[str, Any]:
    """Merge two normalized single-period reports (cur/prev) keyed by dimension
    values into `{dims, current, previous}` rows. `current`/`previous` carry the
    period {start,end,label}. Uses cur's metric list so computed columns merge too.
    """
    met_names: list[str] = cur["metrics"]

    def key(row: dict[str, Any]) -> tuple:
        return tuple(row.get(d) for d in dim_names)

    prev_map = {key(r): r for r in prev["rows"]}
    zeros = {m: 0 for m in met_names}

    rows: list[dict[str, Any]] = []
    seen: set = set()
    for r in cur["rows"]:
        k = key(r)
        seen.add(k)
        pr = prev_map.get(k)
        rows.append(
            {
                "dims": {d: r.get(d) for d in dim_names},
                "current": {m: r.get(m, 0) for m in met_names},
                "previous": {m: pr.get(m, 0) for m in met_names} if pr else dict(zeros),
            }
        )
    for r in prev["rows"]:
        k = key(r)
        if k in seen:
            continue
        rows.append(
            {
                "dims": {d: r.get(d) for d in dim_names},
                "current": dict(zeros),
                "previous": {m: r.get(m, 0) for m in met_names},
            }
        )

    order_field = report_def.get("orderBy")
    if order_field in met_names:
        rows.sort(
            key=lambda x: x["current"].get(order_field, 0),
            reverse=bool(report_def.get("orderDesc", True)),
        )

    return {
        "key": report_def.get("key"),
        "name": report_def.get("name"),
        "dimensions": dim_names,
        "metrics": met_names,
        "current": {**current, "totals": cur["totals"]},
        "previous": {**previous, "totals": prev["totals"]},
        "compared": include_previous,
        "rows": rows,
        "demo": cur.get("demo", False),
    }
