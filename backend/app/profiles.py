"""Saved site profiles, persisted to profiles.json on disk.

A profile is one GA4 site you report on. Add it once; switch between saved
profiles without re-entering anything.

  id                  stable slug (generated from name)
  name                display name (e.g. "TTK")
  propertyId          GA4 numeric property id (required)
  channelGroupDim     custom channel-group dimension API name, e.g.
                      "sessionCustomChannelGroup:1234567" (optional; blank =
                      standard sessionDefaultChannelGroup)
  projectId           GCP project id for quota attribution (optional)
  spreadsheetId       target Google Sheet id for exports (optional)
  slidesId            target Google Slides deck id for the PPT export (optional)
  moengageAppId       MoEngage workspace / app id (MOE-APPKEY header) (optional)
  moengageApiKey      MoEngage DATA API key — SECRET, stored plaintext (optional)
  moengageDataCenter  MoEngage data-center number, e.g. "01" (optional)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

PROFILES_PATH = Path(os.environ.get("PROFILES_FILE", "profiles.json"))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "site"


def _doc_id(value: str) -> str:
    """Accept a full Google Docs/Sheets/Slides URL or a bare ID; return the ID."""
    v = (value or "").strip()
    m = re.search(r"/d/([^/]+)", v)
    return m.group(1) if m else v


def _load() -> list[dict[str, Any]]:
    if PROFILES_PATH.exists():
        try:
            data = json.loads(PROFILES_PATH.read_text())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save(profiles: list[dict[str, Any]]) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(profiles, indent=2))


def all_profiles() -> list[dict[str, Any]]:
    return _load()


def get(profile_id: str) -> dict[str, Any] | None:
    return next((p for p in _load() if p.get("id") == profile_id), None)


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": (data.get("name") or "").strip(),
        "propertyId": str(data.get("propertyId") or "").strip(),
        "channelGroupDim": (data.get("channelGroupDim") or "").strip(),
        "projectId": (data.get("projectId") or "").strip(),
        "spreadsheetId": _doc_id(data.get("spreadsheetId")),
        "slidesId": _doc_id(data.get("slidesId")),
        # MoEngage connector (optional). moengageApiKey is a secret stored in
        # plaintext here, so keep profiles.json out of version control.
        "moengageAppId": (data.get("moengageAppId") or "").strip(),
        "moengageApiKey": (data.get("moengageApiKey") or "").strip(),
        "moengageDataCenter": (data.get("moengageDataCenter") or "").strip(),
        # Ad-platform ids discovered via an OAuth connection (see connections.py);
        # connectionId records which connection they came from.
        "googleAdsCustomerId": (data.get("googleAdsCustomerId") or "").strip(),
        "merchantCenterId": (data.get("merchantCenterId") or "").strip(),
        # Search Console has no numeric propertyId — the site URL is the id.
        "searchConsoleSiteUrl": (data.get("searchConsoleSiteUrl") or "").strip(),
        "metaAdAccountId": (data.get("metaAdAccountId") or "").strip(),
        "connectionId": (data.get("connectionId") or "").strip(),
    }


def create(data: dict[str, Any]) -> dict[str, Any]:
    profiles = _load()
    fields = _normalize(data)
    if not fields["name"] or not fields["propertyId"]:
        raise ValueError("name and propertyId are required")

    base = _slugify(fields["name"])
    pid = base
    n = 2
    existing = {p["id"] for p in profiles}
    while pid in existing:
        pid = f"{base}-{n}"
        n += 1

    profile = {"id": pid, **fields}
    profiles.append(profile)
    _save(profiles)
    return profile


def update(profile_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    profiles = _load()
    for i, p in enumerate(profiles):
        if p["id"] == profile_id:
            fields = _normalize({**p, **data})
            profiles[i] = {"id": profile_id, **fields}
            _save(profiles)
            return profiles[i]
    return None


def delete(profile_id: str) -> bool:
    profiles = _load()
    remaining = [p for p in profiles if p["id"] != profile_id]
    if len(remaining) == len(profiles):
        return False
    _save(remaining)
    return True
