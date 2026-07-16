"""AI-generated insights for a month-over-month report, via Claude.

Produces bullets in the deck style:  → **Headline** — sentence with **bold key numbers**.
Falls back to simple rule-based insights when no ANTHROPIC_API_KEY is set, so the
UI works in demo mode.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .config import settings


class Insight(BaseModel):
    headline: str = Field(description="Short bold phrase, e.g. 'Mobile — Dominates in Volume'")
    body: str = Field(description="One sentence with the key numbers, in the report's currency")


class Insights(BaseModel):
    insights: list[Insight]


def ai_available() -> bool:
    return bool(settings.anthropic_api_key)


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
def _fmt_val(metric: str, value: Any) -> str:
    """Pre-format numbers so the model quotes them verbatim (no error-prone math)."""
    low = metric.lower()
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if "rate" in low:
        return f"{n:.2f}%"
    if "revenue" in low:
        sym = settings.currency_symbol
        if n >= 1e7:
            return f"{sym}{n / 1e7:.2f} Cr"
        if n >= 1e5:
            return f"{sym}{n / 1e5:.2f} lakh"
        return f"{sym}{n:,.0f}"
    return f"{int(n):,}" if n == int(n) else f"{n:,.2f}"


def _table_text(report: dict[str, Any], max_rows: int = 12) -> str:
    dims = report["dimensions"]
    mets = report["metrics"]
    cur_label = report["current"].get("label", "current")
    prev_label = report["previous"].get("label", "previous")
    compared = report.get("compared", True)

    if compared:
        lines = [f"Report: {report.get('name')}", f"Comparing {cur_label} vs {prev_label}", ""]
        header = dims + [f"{m} ({cur_label})" for m in mets] + [f"{m} ({prev_label})" for m in mets]
    else:
        lines = [f"Report: {report.get('name')}", f"Period: {cur_label}", ""]
        header = dims + list(mets)
    lines.append(" | ".join(header))
    for row in report["rows"][:max_rows]:
        vals = [str(row["dims"].get(d, "")) for d in dims]
        vals += [_fmt_val(m, row["current"].get(m, 0)) for m in mets]
        if compared:
            vals += [_fmt_val(m, row["previous"].get(m, 0)) for m in mets]
        lines.append(" | ".join(vals))

    ct = report["current"].get("totals", {})
    lines.append("")
    lines.append("Grand totals " + cur_label + ": " + ", ".join(f"{m}={_fmt_val(m, ct.get(m))}" for m in mets))
    if compared:
        pt = report["previous"].get("totals", {})
        lines.append("Grand totals " + prev_label + ": " + ", ".join(f"{m}={_fmt_val(m, pt.get(m))}" for m in mets))
    return "\n".join(lines)


def _prompt(report: dict[str, Any], variation: int) -> str:
    cur = report["current"].get("label", "current")
    prev = report["previous"].get("label", "previous")
    sym = settings.currency_symbol
    nudge = "" if variation == 0 else (
        f"\n\nThis is regeneration #{variation}: surface DIFFERENT angles than an "
        "obvious first pass — dig into movers, mix shifts, or under-performers."
    )
    compared = report.get("compared", True)
    scope = (
        f"Below is a month-over-month table ({cur} vs {prev})."
        if compared
        else f"Below is a single-period table for {cur} (no comparison)."
    )
    focus = (
        "top performers, best conversion rates, notable month-over-month movements, and revenue drivers"
        if compared
        else "top performers, best conversion rates, and revenue drivers within this period (no month-over-month claims)"
    )
    return (
        f"You are a senior web-analytics analyst writing the insights slide of a monthly "
        f"GA4 report. {scope}\n\n"
        f"{_table_text(report)}\n\n"
        f"Write 2-4 crisp insights a marketing lead would care about: {focus}. Rules:\n"
        f"- Each insight has a short bold 'headline' (e.g. 'Mobile — Dominates in Volume') and "
        f"a one-sentence 'body' citing the specific numbers.\n"
        f"- The numbers in the table are ALREADY FORMATTED (currency in {sym} with lakh/Cr, "
        f"rates as %). Quote them EXACTLY as shown. Do NOT recompute, re-convert, or restate a "
        f"figure in different units — copy the value verbatim.\n"
        f"- You may state a month-over-month direction (up/down) only if it's obvious from the "
        f"two columns; never invent a percentage you didn't compute from the shown values.\n"
        f"- Refer to metrics by natural names (say 'conversion rate', not 'convRate').\n"
        f"- Be concrete and quantitative; no generic filler. No self-corrections like 'actually' "
        f"or 'wait'."
        f"{nudge}"
    )


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def generate(report: dict[str, Any], variation: int = 0) -> dict[str, Any]:
    if not ai_available():
        return {"insights": _fallback(report), "source": "rule-based"}

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=3000,
            thinking={"type": "disabled"},  # structured extraction — no thinking needed
            messages=[{"role": "user", "content": _prompt(report, variation)}],
            output_format=Insights,
        )
        parsed: Insights = response.parsed_output
        return {
            "insights": [i.model_dump() for i in parsed.insights],
            "source": settings.anthropic_model,
        }
    except anthropic.APIError as exc:
        return {"insights": _fallback(report), "source": f"fallback ({exc.__class__.__name__})"}


# --------------------------------------------------------------------------- #
# Rule-based fallback (also used in demo mode)
# --------------------------------------------------------------------------- #
def _fallback(report: dict[str, Any]) -> list[dict[str, str]]:
    mets = report["metrics"]
    rows = report["rows"]
    dims = report["dimensions"]
    if not rows:
        return [{"headline": "No data", "body": "No rows were returned for this period."}]

    def label(row: dict[str, Any]) -> str:
        return " / ".join(str(row["dims"].get(d, "")) for d in dims if row["dims"].get(d))

    out: list[dict[str, str]] = []
    # Volume leader by the first metric.
    vol_metric = mets[0]
    top = max(rows, key=lambda r: r["current"].get(vol_metric, 0))
    out.append({
        "headline": f"{label(top)} — Volume Leader",
        "body": f"{label(top)} led with {top['current'].get(vol_metric, 0):,} {vol_metric} "
                f"in {report['current'].get('label', 'this period')}.",
    })
    # Revenue driver if a revenue metric exists.
    rev = next((m for m in mets if "revenue" in m.lower()), None)
    if rev:
        top_rev = max(rows, key=lambda r: r["current"].get(rev, 0))
        out.append({
            "headline": f"{label(top_rev)} — Top Revenue",
            "body": f"{label(top_rev)} generated {settings.currency_symbol}"
                    f"{top_rev['current'].get(rev, 0):,.0f} in {rev}.",
        })
    return out
