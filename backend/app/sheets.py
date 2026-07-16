"""Write report data to a Google Sheet — one tab per report.

The target spreadsheet must be shared with the service-account email (Editor).
"""
from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build

from .ga4 import get_credentials


def _service(project_id: str | None = None):
    # cache_discovery=False avoids a noisy warning on some setups.
    return build(
        "sheets", "v4", credentials=get_credentials(project_id), cache_discovery=False
    )


def report_to_values(report: dict[str, Any]) -> list[list[Any]]:
    """Flatten a normalized report into a 2D array: header row + data rows."""
    columns: list[str] = list(report.get("dimensions", [])) + list(report.get("metrics", []))
    values: list[list[Any]] = [columns]
    for row in report.get("rows", []):
        values.append([row.get(c, "") for c in columns])
    return values


def export(
    spreadsheet_id: str,
    tabs: list[tuple[str, list[list[Any]]]],
    date_note: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Write each (tab_name, values) pair to its own tab, creating tabs as needed.

    Existing tab contents are cleared first so each export is a clean snapshot.
    """
    svc = _service(project_id)
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}

    # Create any missing tabs in one batch.
    add_requests = [
        {"addSheet": {"properties": {"title": tab}}}
        for tab, _ in tabs
        if tab not in existing
    ]
    if add_requests:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": add_requests}
        ).execute()

    written: list[str] = []
    for tab, values in tabs:
        # Optionally stamp the date range on the first row.
        body_values = values
        if date_note:
            body_values = [[f"Date range: {date_note}"], [], *values]
        svc.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"'{tab}'"
        ).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            body={"values": body_values},
        ).execute()
        written.append(tab)

    return {
        "spreadsheetId": spreadsheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
        "tabs": written,
    }
