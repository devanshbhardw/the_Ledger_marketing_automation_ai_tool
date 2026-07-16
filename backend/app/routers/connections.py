"""OAuth connections: list/discover/delete + Google and Meta login flows."""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from .. import cache
from .. import connections as store
from .. import google_oauth, meta_oauth
from ..config import settings

router = APIRouter(tags=["connections"])

logger = logging.getLogger(__name__)

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Discovery hits 2-4 provider APIs per connection (seconds of latency), so the
# full result is cached and pages are served from the cache.
DISCOVERY_TTL_SECONDS = 600


def _discovery_key(connection_id: str) -> str:
    return f"ttk:discovery:{connection_id}"


def _forget_discovery(connection_id: str) -> None:
    try:
        cache.client().delete(_discovery_key(connection_id))
    except Exception:  # noqa: BLE001 — cache is best-effort
        pass


def _frontend_connections_url(**query: str) -> str:
    """The frontend page users land on after OAuth (same origin as callback)."""
    parts = urlsplit(settings.google_oauth_redirect_uri)
    url = f"{parts.scheme}://{parts.netloc}/connections"
    return f"{url}?{urlencode(query)}" if query else url


@router.get("/connections")
def list_connections():
    return {"connections": store.list_connections()}


@router.get("/connections/{connection_id}/properties")
def discover_properties(
    connection_id: str, page: int = 1, pageSize: int = 0, refresh: bool = False
):
    """Discovered accounts, cached for DISCOVERY_TTL_SECONDS.

    pageSize=0 (default) returns everything; pageSize>0 returns that page.
    refresh=true bypasses the cache and re-queries the providers.
    """
    conn = store.get_connection(connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    props = None
    if not refresh:
        cached = cache.get(_discovery_key(connection_id))
        if cached is not None:
            props = cached.get("properties")
    if props is None:
        module = google_oauth if conn["provider"] == "google" else meta_oauth
        try:
            props = module.discover_properties(connection_id)
        except ValueError as exc:  # decryption / missing-refresh-token errors
            raise HTTPException(status_code=409, detail=str(exc))
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"{conn['provider']} API error: {exc.response.text[:300]}",
            )
        cache.set(
            _discovery_key(connection_id), {"properties": props},
            ttl=DISCOVERY_TTL_SECONDS,
        )

    total = len(props)
    if pageSize > 0:
        page = max(page, 1)
        start = (page - 1) * pageSize
        return {
            "properties": props[start : start + pageSize],
            "total": total,
            "page": page,
            "pageSize": pageSize,
            "hasMore": start + pageSize < total,
        }
    return {"properties": props, "total": total}


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: str):
    conn = store.get_connection(connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    _revoke(connection_id, conn["provider"])
    store.delete_connection(connection_id)
    _forget_discovery(connection_id)
    return {"ok": True}


def _revoke(connection_id: str, provider: str) -> None:
    """Best-effort token revocation at the provider before deleting locally."""
    try:
        token = store.get_valid_access_token(connection_id)
        if provider == "google":
            httpx.post(GOOGLE_REVOKE_URL, params={"token": token}, timeout=15)
        else:
            httpx.delete(
                f"{meta_oauth.GRAPH_URL}/me/permissions",
                params={"access_token": token},
                timeout=15,
            )
    except Exception as exc:  # noqa: BLE001 — deletion must not be blocked
        logger.warning("token revocation failed for %s: %s", connection_id, exc)


# --------------------------------------------------------------------------- #
# OAuth flows
# --------------------------------------------------------------------------- #
# CSRF states from /login, consumed by the matching /callback.
_pending_states: set[str] = set()


def _new_state() -> str:
    state = secrets.token_urlsafe(24)
    _pending_states.add(state)
    return state


def _callback(module, provider: str, code: str | None, state: str, error: str):
    if error or not code:
        return RedirectResponse(
            _frontend_connections_url(error=error or "missing code"), status_code=302
        )
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    _pending_states.discard(state)
    try:
        conn = module.exchange_code(code)
        # Re-authorizing may change scopes — drop any stale discovery cache.
        _forget_discovery(conn["id"])
    except httpx.HTTPStatusError as exc:
        logger.warning("%s code exchange failed: %s", provider, exc.response.text[:300])
        return RedirectResponse(
            _frontend_connections_url(error=f"{provider} token exchange failed"),
            status_code=302,
        )
    return RedirectResponse(_frontend_connections_url(), status_code=302)


@router.get("/oauth/google/login")
def google_login():
    return RedirectResponse(google_oauth.build_auth_url(_new_state()), status_code=302)


@router.get("/oauth/google/callback")
def google_callback(code: str = "", state: str = "", error: str = ""):
    return _callback(google_oauth, "google", code, state, error)


@router.get("/oauth/meta/login")
def meta_login():
    return RedirectResponse(meta_oauth.build_auth_url(_new_state()), status_code=302)


@router.get("/oauth/meta/callback")
def meta_callback(code: str = "", state: str = "", error: str = ""):
    return _callback(meta_oauth, "meta", code, state, error)
