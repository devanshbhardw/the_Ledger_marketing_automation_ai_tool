"""Google OAuth flow + account discovery for connected Google accounts.

Unlike ga4.py (which uses service-account keys), everything here acts as the
signed-in user: the consent screen grants Analytics / Ads / Merchant Center
read access, and discovery lists whatever that user's account can see.

Flow:  build_auth_url() -> user consents -> callback hits exchange_code(),
which stores tokens via connections.py -> discover_properties() enumerates
GA4 properties, Google Ads accounts and Merchant Center accounts.
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
from google.oauth2.credentials import Credentials

from . import connections
from .config import settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/content",
    # Read-only Search Console access, for sites.list discovery below. Often
    # granted incidentally by another scope, but request it explicitly so the
    # consent screen and stored grant reflect it as an intentional ask.
    "https://www.googleapis.com/auth/webmasters.readonly",
    # Needed to label the connection with the signed-in account's email.
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

ADS_API_URL = "https://googleads.googleapis.com/v18/customers:listAccessibleCustomers"
CONTENT_API_URL = "https://shoppingcontent.googleapis.com/content/v2.1"
SEARCH_CONSOLE_API_URL = "https://www.googleapis.com/webmasters/v3/sites"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def build_auth_url(state: str) -> str:
    """URL for Google's OAuth consent screen; redirect the user here."""
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # offline + consent so Google returns a refresh token.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    """Trade the callback's auth code for tokens and persist the connection."""
    resp = httpx.post(
        connections.GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_oauth_redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()

    return connections.save_connection(
        {
            "provider": "google",
            "accountEmailOrName": _account_email(tok),
            "accessToken": tok["access_token"],
            "refreshToken": tok.get("refresh_token", ""),
            "expiresAt": int(time.time()) + int(tok.get("expires_in") or 3600),
            "scopes": tok.get("scope", " ".join(SCOPES)),
        }
    )


def _account_email(tok: dict[str, Any]) -> str:
    """Signed-in account's email, from the id_token or the userinfo endpoint."""
    id_token = tok.get("id_token") or ""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if claims.get("email"):
            return claims["email"]
    except (IndexError, ValueError):
        pass
    resp = httpx.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {tok['access_token']}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("email") or "google-account"


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #

def discover_properties(connection_id: str) -> list[dict[str, Any]]:
    """All GA4 / Google Ads / Merchant Center accounts the connection can see.

    Each source is best-effort: a failing API (scope not granted, API not
    enabled, missing Ads developer token) is logged and skipped so the others
    still return.
    """
    token = connections.get_valid_access_token(connection_id)
    out: list[dict[str, Any]] = []
    started = time.monotonic()

    # The four sources are independent, so fan them out concurrently rather
    # than paying each one's latency in series. Each stays best-effort: a
    # failing source is logged and skipped so the others still return.
    sources = (_ga4_properties, _ads_accounts, _merchant_accounts, _search_console_sites)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {executor.submit(fn, token): fn for fn in sources}
        for future in concurrent.futures.as_completed(futures):
            fn = futures[future]
            try:
                out.extend(future.result())
            except Exception as exc:  # noqa: BLE001 — isolate per-source failures
                logger.warning("%s failed for %s: %s", fn.__name__, connection_id, exc)

    logger.info(
        "discover_properties(%s) returned %d properties in %.2fs",
        connection_id, len(out), time.monotonic() - started,
    )
    return out


def _ga4_properties(token: str) -> list[dict[str, Any]]:
    client = AnalyticsAdminServiceClient(credentials=Credentials(token=token))
    out = []
    for acct in client.list_account_summaries():
        for prop in acct.property_summaries:
            pid = prop.property.split("/")[-1]
            out.append(
                {
                    "provider": "google",
                    "type": "ga4",
                    "externalId": pid,
                    "displayName": prop.display_name,
                    "accountName": acct.display_name,
                    # Same shape as ga4.list_properties() so the frontend can
                    # treat OAuth-discovered properties identically.
                    "account": acct.display_name,
                    "propertyId": pid,
                    "projectId": "",
                }
            )
    return out


def _ads_accounts(token: str) -> list[dict[str, Any]]:
    if not settings.google_ads_developer_token:
        logger.info("GOOGLE_ADS_DEVELOPER_TOKEN unset — skipping Ads discovery")
        return []
    resp = httpx.get(
        ADS_API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "developer-token": settings.google_ads_developer_token,
        },
        timeout=10,
    )
    resp.raise_for_status()
    out = []
    for name in resp.json().get("resourceNames", []):  # "customers/1234567890"
        cid = name.split("/")[-1]
        out.append(
            {
                "provider": "google",
                "type": "google_ads",
                "externalId": cid,
                # listAccessibleCustomers returns ids only; show a formatted id.
                "displayName": f"{cid[:3]}-{cid[3:6]}-{cid[6:]}" if len(cid) == 10 else cid,
                "accountName": "",
            }
        )
    return out


def _merchant_accounts(token: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(f"{CONTENT_API_URL}/accounts/authinfo", headers=headers, timeout=10)
    resp.raise_for_status()

    ids = []
    for ident in resp.json().get("accountIdentifiers", []):
        mid = str(ident.get("merchantId") or ident.get("aggregatorId") or "")
        if mid:
            ids.append(mid)

    def _display_name(mid: str) -> str:
        """Best-effort display name; the id alone is still usable on failure.

        Per-call 10s timeout so one slow/hanging account can't stall the whole
        lookup — a timeout is treated like any other error and falls back to
        the "Merchant Center <id>" placeholder built by the caller.
        """
        try:
            info = httpx.get(
                f"{CONTENT_API_URL}/{mid}/accounts/{mid}", headers=headers, timeout=10
            )
            if info.status_code == 200:
                return info.json().get("name", "")
        except httpx.HTTPError:
            pass
        return ""

    # These lookups are independent, so fan them out instead of paying each
    # account's round-trip in series (was the dominant cost of discovery).
    if ids:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            names = list(executor.map(_display_name, ids))
    else:
        names = []

    out = []
    for mid, name in zip(ids, names):
        out.append(
            {
                "provider": "google",
                "type": "merchant_center",
                "externalId": mid,
                "displayName": name or f"Merchant Center {mid}",
                "accountName": name,
            }
        )
    return out


def _search_console_sites(token: str) -> list[dict[str, Any]]:
    resp = httpx.get(
        SEARCH_CONSOLE_API_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    out = []
    for site in resp.json().get("siteEntry", []):
        # Skip sites the user can't actually pull data for.
        if site.get("permissionLevel") == "siteUnverifiedUser":
            continue
        site_url = site.get("siteUrl") or ""
        if not site_url:
            continue
        out.append(
            {
                "provider": "google",
                "type": "search_console",
                "externalId": site_url,
                "displayName": site_url,
                "accountName": site_url,
            }
        )
    return out
