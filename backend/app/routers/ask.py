"""Free-text Q&A over a site's data — Claude queries the APIs itself.

Claude always gets two GA4 tools: get_ga4_metadata (what fields exist on this
property) and run_ga4_report (arbitrary dimensions/metrics via ga4_query). When
the profile also has a Search Console site or a Merchant Center account
configured, it additionally gets run_search_console_report and/or
run_merchant_center_report — offered only when the corresponding ID is present,
since a tool the profile can't back would just error. It composes its own
queries, retries on API compatibility errors, and answers from the numbers it
actually retrieved.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from .. import (
    ask_history,
    ga4_query,
    insights,
    merchant_center_query,
    profiles,
    search_console_query,
)
from ..config import settings

router = APIRouter(prefix="/ask", tags=["ask"])


@router.get("/history/all")
def get_all_history(limit: int = 200):
    return {"history": ask_history.list_all(limit=limit)}


@router.get("/history")
def get_history(profileId: str, limit: int = 50):
    if profiles.get(profileId) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"history": ask_history.list_for(profileId, limit=limit)}


@router.delete("/history")
def clear_history(profileId: str):
    return {"ok": True, "removed": ask_history.clear(profileId)}

log = logging.getLogger("ttk.ask")

MAX_TOOL_ROUNDS = 6

GA4_TOOLS = [
    {
        "name": "get_ga4_metadata",
        "description": (
            "List every dimension and metric available on this GA4 property "
            "(standard + custom), as {apiName, displayName}. Call this if "
            "you're unsure what fields exist or what they're called."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_ga4_report",
        "description": (
            "Run a GA4 Data API report on this property. Returns rows, grand "
            "totals and rowCount — or {error} if GA4 rejects the query (e.g. "
            "incompatible dimension/metric combination); read the error and "
            "retry with corrected parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "GA4 dimension API names, e.g. [\"city\", \"newVsReturning\"]",
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "GA4 metric API names, e.g. [\"sessions\", \"totalRevenue\"]",
                },
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                "dimension_filter": {
                    "type": "object",
                    "description": "Optional filter on one dimension",
                    "properties": {
                        "dimension": {"type": "string"},
                        "value": {"type": "string"},
                        "match": {"type": "string", "enum": ["equals", "contains"]},
                    },
                    "required": ["dimension", "value"],
                },
                "limit": {"type": "integer", "description": "Max rows (default 50, max 250)"},
            },
            "required": ["metrics", "start_date", "end_date"],
        },
    },
]

SEARCH_CONSOLE_TOOL = {
    "name": "run_search_console_report",
    "description": (
        "Run a Google Search Console Search Analytics report for this site — "
        "ORGANIC search data only (Google search queries, landing pages, "
        "countries, devices, rankings), NOT GA4 and NOT Shopping. Every row "
        "always includes clicks, impressions, ctr and position; you only "
        "choose how to break them down. Returns rows and rowCount, or {error} "
        "on a bad request — read the error and retry."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": ["query", "page", "country", "device", "date"]},
                "description": "How to break down results, e.g. [\"query\"] or [\"page\",\"device\"]",
            },
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "dimension_filter": {
                "type": "object",
                "description": "Optional filter on one dimension",
                "properties": {
                    "dimension": {"type": "string"},
                    "value": {"type": "string"},
                    "match": {"type": "string", "enum": ["equals", "contains"]},
                },
                "required": ["dimension", "value"],
            },
            "limit": {"type": "integer", "description": "Max rows (default 50)"},
        },
        "required": ["dimensions", "start_date", "end_date"],
    },
}

MERCHANT_CENTER_TOOL = {
    "name": "run_merchant_center_report",
    "description": (
        "Run a Google Merchant Center product-performance report for this "
        "account — Shopping/product data only (clicks, impressions, "
        "conversions per product from the ProductPerformanceView), NOT GA4 "
        "and NOT organic Search Console. Provide the report fields to select. "
        "Returns rows and rowCount, or {error} on a bad query — read the "
        "error and retry with corrected fields."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "select_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "ProductPerformanceView fields to select, e.g. "
                    "[\"segments.offer_id\", \"metrics.clicks\", \"metrics.impressions\"]"
                ),
            },
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "dimension_filter": {
                "type": "object",
                "description": "Optional filter on one field",
                "properties": {
                    "dimension": {"type": "string"},
                    "value": {"type": "string"},
                    "match": {"type": "string", "enum": ["equals", "contains"]},
                },
                "required": ["dimension", "value"],
            },
            "limit": {"type": "integer", "description": "Max rows (default 50)"},
        },
        "required": ["select_fields", "start_date", "end_date"],
    },
}


def _tools_for(profile: dict) -> list[dict]:
    """GA4 tools always; the Search Console / Merchant Center tools only when
    the profile carries the ID that backs them."""
    tools = list(GA4_TOOLS)
    if (profile.get("searchConsoleSiteUrl") or "").strip():
        tools.append(SEARCH_CONSOLE_TOOL)
    if (profile.get("merchantCenterId") or "").strip():
        tools.append(MERCHANT_CENTER_TOOL)
    return tools


def _run_tool(profile: dict, name: str, tool_input: dict) -> str:
    """Execute one tool call; errors come back as result payloads, never raises."""
    try:
        if name == "get_ga4_metadata":
            result = ga4_query.get_metadata(profile)
        elif name == "run_ga4_report":
            result = ga4_query.run_dynamic_report(
                profile,
                dimensions=list(tool_input.get("dimensions") or []),
                metrics=list(tool_input.get("metrics") or []),
                start_date=str(tool_input.get("start_date") or ""),
                end_date=str(tool_input.get("end_date") or ""),
                dimension_filter=tool_input.get("dimension_filter") or None,
                limit=int(tool_input.get("limit") or 50),
            )
        elif name == "run_search_console_report":
            result = search_console_query.run_report(
                profile,
                dimensions=list(tool_input.get("dimensions") or []),
                start_date=str(tool_input.get("start_date") or ""),
                end_date=str(tool_input.get("end_date") or ""),
                dimension_filter=tool_input.get("dimension_filter") or None,
                limit=int(tool_input.get("limit") or 50),
            )
        elif name == "run_merchant_center_report":
            result = merchant_center_query.run_report(
                profile,
                select_fields=list(tool_input.get("select_fields") or []),
                start_date=str(tool_input.get("start_date") or ""),
                end_date=str(tool_input.get("end_date") or ""),
                dimension_filter=tool_input.get("dimension_filter") or None,
                limit=int(tool_input.get("limit") or 50),
            )
        else:
            result = {"error": f"unknown tool '{name}'"}
    except Exception as exc:  # noqa: BLE001 — feed failures back to the model
        log.warning("ask: tool %s failed for %s: %s", name, profile.get("id"), exc)
        result = {"error": str(exc)}
    return json.dumps(result, separators=(",", ":"), default=str)


@router.post("")
def ask(data: dict = Body(...)):
    profile_id = (data.get("profileId") or "").strip()
    question = (data.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Unlike insights.py there is no rule-based fallback here: free-text Q&A
    # without a model would just be wrong answers.
    if not insights.ai_available():
        raise HTTPException(
            status_code=501,
            detail="Ask requires an Anthropic API key. Set ANTHROPIC_API_KEY in "
            "backend/.env to enable free-text questions about this site's data.",
        )

    if not (profile.get("propertyId") or "").strip():
        return {
            "answer": f"{profile.get('name', 'This site')} has no GA4 property "
            "configured, so there is no analytics data to query. Add a GA4 "
            "property ID to the site to enable Ask."
        }

    system = (
        f"You are answering questions about {profile.get('name', 'this site')}'s "
        "GA4 analytics by directly querying the Google Analytics Data API. "
        "Call get_ga4_metadata if you're unsure what dimensions/metrics exist. "
        "Call run_ga4_report to get real data — you can call it multiple times "
        "to build up a multi-dimensional answer (e.g. city x customer-type "
        'needs one query with dimensions ["city","newVsReturning"] and '
        "relevant funnel metrics). If a query errors, read the error and retry "
        f"with corrected parameters. Today's date is {date.today().isoformat()}; "
        "resolve relative date ranges yourself. Once you have enough data, "
        "answer the question directly and specifically — cite the actual "
        "numbers you retrieved.\n"
        "Format the answer in GitHub-flavored Markdown for a non-technical "
        "reader: lead with a 1-2 sentence takeaway, then a compact table for "
        "any per-segment numbers (max ~8 rows and 4-5 columns — pick the "
        "columns that answer the question, don't dump every metric). Round "
        "large numbers. Avoid dense parenthetical asides."
    )

    extra_sources = []
    if (profile.get("searchConsoleSiteUrl") or "").strip():
        extra_sources.append(
            "run_search_console_report for Google Search Console data — organic "
            "search performance (search queries, landing pages, countries, "
            "devices, and their clicks/impressions/ctr/average position/rankings)"
        )
    if (profile.get("merchantCenterId") or "").strip():
        extra_sources.append(
            "run_merchant_center_report for Google Merchant Center data — "
            "Shopping product performance (per-product clicks, impressions and "
            "conversions from the ProductPerformanceView)"
        )
    if extra_sources:
        system += (
            "\nThis site also has other data sources available via separate "
            "tools: " + "; ".join(extra_sources) + ". These are DISTINCT from "
            "GA4 and from each other — Search Console is organic Google search, "
            "Merchant Center is Shopping products — so pick the tool that "
            "matches the question and don't conflate their data. Use GA4 for "
            "on-site behaviour and traffic."
        )

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tools = _tools_for(profile)
    messages: list[dict] = [{"role": "user", "content": question}]
    response = None
    try:
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2000,
                system=system,
                tools=tools,
                messages=messages,
            )
            if response.stop_reason != "tool_use":
                break
            if round_no == MAX_TOOL_ROUNDS:
                break  # out of rounds — fall through with whatever text exists
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _run_tool(profile, block.name, block.input),
                    }
                    for block in response.content
                    if block.type == "tool_use"
                ],
            })
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}")

    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "tool_use":
        answer = (answer + "\n\n" if answer else "") + (
            "Note: this answer may be incomplete — the question needed more "
            "data queries than allowed in one go. Try asking something more "
            "specific."
        )
    elif not answer:
        answer = "I couldn't produce an answer from the available data."
    ask_history.add(profile_id, question, answer)
    return {"answer": answer}
