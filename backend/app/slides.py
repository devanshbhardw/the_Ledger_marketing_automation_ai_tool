"""Build a branded Google Slides deck from report comparisons + AI insights.

Reproduces the monthly-report template: orange titles, a yellow-header
month-over-month table per report, and an insights slide with bold headlines.
The target deck (profile.slidesId) must be shared with the service account as Editor.
"""
from __future__ import annotations

import uuid
from typing import Any

from googleapiclient.discovery import build

from .ga4 import get_credentials

# Brand colors (from the template).
ORANGE = "#EB6834"
YELLOW = "#FCE5A0"
DARKTEXT = "#0B0B0B"

EMU = "EMU"
PAGE_W = 9144000
PAGE_H = 5143500
TABLE_W = 8300000  # table width; leaves ~400000 EMU margin each side of the page


def _svc(project_id: str | None = None):
    return build(
        "slides", "v1", credentials=get_credentials(project_id), cache_discovery=False
    )


def _rgb(hex_color: str) -> dict[str, float]:
    h = hex_color.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _size(w: int, h: int) -> dict[str, Any]:
    return {"width": {"magnitude": w, "unit": EMU}, "height": {"magnitude": h, "unit": EMU}}


def _xf(x: int, y: int) -> dict[str, Any]:
    return {"scaleX": 1, "scaleY": 1, "translateX": x, "translateY": y, "unit": EMU}


class _Deck:
    """Accumulates batchUpdate requests with unique object ids."""

    def __init__(self) -> None:
        self.reqs: list[dict[str, Any]] = []
        self._n = 0
        # Per-run namespace so regenerated object ids never collide with objects
        # left in the deck from a previous export (deletes happen later in the
        # same batch, but createSlide is validated first).
        self._run = uuid.uuid4().hex[:8]

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"ttk_{self._run}_{prefix}_{self._n}"

    def add_slide(self) -> str:
        sid = self._id("slide")
        self.reqs.append({"createSlide": {"objectId": sid,
                                           "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        return sid

    def add_title(self, slide: str, text: str) -> None:
        tid = self._id("title")
        self.reqs.append({"createShape": {"objectId": tid, "shapeType": "TEXT_BOX",
                                           "elementProperties": {"pageObjectId": slide,
                                                                 "size": _size(8300000, 700000),
                                                                 "transform": _xf(400000, 250000)}}})
        self.reqs.append({"insertText": {"objectId": tid, "insertionIndex": 0, "text": text}})
        self.reqs.append({"updateTextStyle": {"objectId": tid, "textRange": {"type": "ALL"},
                                               "style": {"fontSize": {"magnitude": 24, "unit": "PT"},
                                                         "bold": True,
                                                         "foregroundColor": {"opaqueColor": {"rgbColor": _rgb(ORANGE)}}},
                                               "fields": "fontSize,bold,foregroundColor"}})

    def add_text(self, slide: str, text: str, y: int, size_pt: int = 12, height: int = 500000) -> str:
        bid = self._id("text")
        self.reqs.append({"createShape": {"objectId": bid, "shapeType": "TEXT_BOX",
                                           "elementProperties": {"pageObjectId": slide,
                                                                 "size": _size(8300000, height),
                                                                 "transform": _xf(400000, y)}}})
        if text:
            self.reqs.append({"insertText": {"objectId": bid, "insertionIndex": 0, "text": text}})
            self.reqs.append({"updateTextStyle": {"objectId": bid, "textRange": {"type": "ALL"},
                                                   "style": {"fontSize": {"magnitude": size_pt, "unit": "PT"}},
                                                   "fields": "fontSize"}})
        return bid

    def add_table(self, slide: str, header: list[str], rows: list[list[str]], n_dims: int = 1) -> None:
        n_rows = len(rows) + 1
        n_cols = len(header)
        tid = self._id("table")
        self.reqs.append({"createTable": {"objectId": tid,
                                          "elementProperties": {"pageObjectId": slide,
                                                                "size": _size(TABLE_W, 2600000),
                                                                "transform": _xf(400000, 1100000)},
                                          "rows": n_rows, "columns": n_cols}})
        # createTable ignores the size hint for column widths and gives every
        # column a wide default, so 12 columns overflow the slide. Set explicit
        # widths that sum to TABLE_W — dimension columns (text) wider than the
        # numeric metric columns. First dim (e.g. product name) widest of all.
        weights = [3 if c == 0 else 2 for c in range(n_dims)] + [1] * (n_cols - n_dims)
        unit = TABLE_W / sum(weights)
        for c, w in enumerate(weights):
            self.reqs.append({"updateTableColumnProperties": {"objectId": tid,
                                                              "columnIndices": [c],
                                                              "tableColumnProperties": {"columnWidth": {"magnitude": int(unit * w), "unit": EMU}},
                                                              "fields": "columnWidth"}})
        grid = [header] + rows
        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                text = "" if val is None else str(val)
                if not text:
                    # Empty cell: no text to insert, and styling a text-less cell
                    # makes updateTextStyle fail ("object has no text").
                    continue
                self.reqs.append({"insertText": {"objectId": tid,
                                                 "cellLocation": {"rowIndex": r, "columnIndex": c},
                                                 "insertionIndex": 0, "text": text}})
                self.reqs.append({"updateTextStyle": {"objectId": tid,
                                                      "cellLocation": {"rowIndex": r, "columnIndex": c},
                                                      "textRange": {"type": "ALL"},
                                                      "style": {"fontSize": {"magnitude": 7, "unit": "PT"},
                                                                "bold": r == 0},
                                                      "fields": "fontSize,bold"}})
        # Yellow header row fill.
        self.reqs.append({"updateTableCellProperties": {"objectId": tid,
                                                        "tableRange": {"location": {"rowIndex": 0, "columnIndex": 0},
                                                                       "rowSpan": 1, "columnSpan": n_cols},
                                                        "tableCellProperties": {"tableCellBackgroundFill": {"solidFill": {"color": {"rgbColor": _rgb(YELLOW)}}}},
                                                        "fields": "tableCellBackgroundFill.solidFill.color"}})

    def add_insights(self, slide: str, insights: list[dict[str, str]]) -> None:
        bid = self._id("ins")
        self.reqs.append({"createShape": {"objectId": bid, "shapeType": "TEXT_BOX",
                                          "elementProperties": {"pageObjectId": slide,
                                                                "size": _size(8300000, 3500000),
                                                                "transform": _xf(400000, 1200000)}}})
        # Build the full text, tracking headline ranges to bold.
        full = ""
        bold_ranges: list[tuple[int, int]] = []
        for ins in insights:
            head = f"→ {ins.get('headline', '')}"
            start = len(full)
            full += head
            bold_ranges.append((start, len(full)))
            full += f"  {ins.get('body', '')}\n\n"
        if not full:
            full = "No insights available."
        self.reqs.append({"insertText": {"objectId": bid, "insertionIndex": 0, "text": full}})
        self.reqs.append({"updateTextStyle": {"objectId": bid, "textRange": {"type": "ALL"},
                                              "style": {"fontSize": {"magnitude": 14, "unit": "PT"},
                                                        "foregroundColor": {"opaqueColor": {"rgbColor": _rgb(DARKTEXT)}}},
                                              "fields": "fontSize,foregroundColor"}})
        for s, e in bold_ranges:
            self.reqs.append({"updateTextStyle": {"objectId": bid,
                                                  "textRange": {"type": "FIXED_RANGE", "startIndex": s, "endIndex": e},
                                                  "style": {"bold": True},
                                                  "fields": "bold"}})


def _dim_label(d: str) -> str:
    """Human-readable column header for a dimension token."""
    if d == "{channelGroup}":
        return "Channel Group"
    return d


def _num(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return str(v)


def build_deck(
    slides_id: str,
    site_name: str,
    sections: list[dict[str, Any]],
    project_id: str | None = None,
) -> dict[str, Any]:
    """sections: [{name, report(comparison dict), insights: [{headline, body}]}]"""
    svc = _svc(project_id)
    pres = svc.presentations().get(presentationId=slides_id).execute()
    old_ids = [s["objectId"] for s in pres.get("slides", [])]

    deck = _Deck()
    period = ""
    if sections:
        r0 = sections[0]["report"]
        period = f"{r0['current'].get('label')} vs {r0['previous'].get('label')}"

    # Title slide.
    title_slide = deck.add_slide()
    deck.add_title(title_slide, f"{site_name} — GA4 Report")
    deck.add_text(title_slide, period, y=1100000, size_pt=18)

    # Per report: table slide + insights slide.
    for sec in sections:
        report = sec["report"]
        dims, mets = report["dimensions"], report["metrics"]

        # Keep headers short so 12+ columns fit the slide. The period is already
        # on the title slide, so distinguish current vs previous with "(prev)"
        # instead of repeating the date range in every metric column.
        header = [_dim_label(d) for d in dims] + list(mets) + [f"{m} (prev)" for m in mets]
        table_rows: list[list[str]] = []
        for row in report["rows"][:10]:  # top 10 rows + a Grand Total row (appended below)
            line = [str(row["dims"].get(d, "")) for d in dims]
            line += [_num(row["current"].get(m, 0)) for m in mets]
            line += [_num(row["previous"].get(m, 0)) for m in mets]
            table_rows.append(line)
        ct, pt = report["current"].get("totals", {}), report["previous"].get("totals", {})
        total = ["Grand Total"] + [""] * (len(dims) - 1)
        total += [_num(ct.get(m, 0)) for m in mets] + [_num(pt.get(m, 0)) for m in mets]
        table_rows.append(total)

        ts = deck.add_slide()
        deck.add_title(ts, f"{sec['name']} — GA4")
        deck.add_table(ts, header, table_rows, n_dims=len(dims))

        isl = deck.add_slide()
        deck.add_title(isl, f"{sec['name']} — Insights")
        deck.add_insights(isl, sec.get("insights", []))

    # Remove the deck's prior slides so each export is a clean rebuild.
    for oid in old_ids:
        deck.reqs.append({"deleteObject": {"objectId": oid}})

    svc.presentations().batchUpdate(presentationId=slides_id, body={"requests": deck.reqs}).execute()
    return {"slidesId": slides_id,
            "url": f"https://docs.google.com/presentation/d/{slides_id}/edit",
            "slides": 1 + 2 * len(sections)}
