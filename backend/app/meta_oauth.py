"""Meta (Facebook) OAuth flow + ad-account discovery, mirroring google_oauth.py.

Meta has no refresh tokens: the callback's short-lived token is immediately
exchanged for a ~60-day long-lived one, which connections.py re-exchanges
before it expires.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx

from . import connections
from .config import settings

GRAPH_URL = "https://graph.facebook.com/v21.0"
AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"

SCOPES = ["ads_read", "business_management"]


def build_auth_url(state: str) -> str:
    """URL for Meta's OAuth consent dialog; redirect the user here."""
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    """Trade the callback's auth code for a long-lived token and persist it."""
    resp = httpx.get(
        f"{GRAPH_URL}/oauth/access_token",
        params={
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "redirect_uri": settings.meta_redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    short = resp.json()

    # Upgrade to a long-lived (~60 day) token right away.
    resp = httpx.get(
        connections.META_TOKEN_URL,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": short["access_token"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()

    me = httpx.get(
        f"{GRAPH_URL}/me",
        params={"fields": "name", "access_token": tok["access_token"]},
        timeout=30,
    )
    me.raise_for_status()

    return connections.save_connection(
        {
            "provider": "meta",
            "accountEmailOrName": me.json().get("name") or "meta-account",
            "accessToken": tok["access_token"],
            "refreshToken": "",
            "expiresAt": int(time.time()) + int(tok.get("expires_in") or 5184000),
            "scopes": ",".join(SCOPES),
        }
    )


def discover_properties(connection_id: str) -> list[dict[str, Any]]:
    """Ad accounts the connected Meta user can access, in the unified shape."""
    token = connections.get_valid_access_token(connection_id)
    out: list[dict[str, Any]] = []
    url = f"{GRAPH_URL}/me/adaccounts"
    params: dict[str, Any] = {
        "fields": "account_id,name,business{name}",
        "limit": 100,
        "access_token": token,
    }
    while url:
        resp = httpx.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for acct in data.get("data", []):
            out.append(
                {
                    "provider": "meta",
                    "type": "meta_ads",
                    "externalId": acct.get("account_id", ""),
                    "displayName": acct.get("name") or acct.get("account_id", ""),
                    "accountName": (acct.get("business") or {}).get("name", ""),
                }
            )
        # Graph pagination: `next` is a full URL that already carries params.
        url = data.get("paging", {}).get("next")
        params = {}
    return out
