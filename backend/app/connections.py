"""OAuth connections, persisted to connections.json on disk.

A connection is one authorized Google or Meta account, used to discover the
GA4 properties / ad accounts that account can access.

  id                  stable slug (generated from provider + account)
  provider            "google" | "meta"
  accountEmailOrName  the signed-in account's email (Google) or name (Meta)
  accessToken         encrypted with Fernet (settings.token_encryption_key)
  refreshToken        encrypted; empty for Meta (long-lived tokens instead)
  expiresAt           unix epoch seconds when accessToken expires (0 = unknown)
  scopes              space-separated granted scopes
  createdAt           unix epoch seconds

Tokens are only ever stored encrypted; use get_valid_access_token() to read a
plaintext token — it auto-refreshes via the provider's token endpoint when
the stored one is expired.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

CONNECTIONS_PATH = Path(os.environ.get("CONNECTIONS_FILE", "connections.json"))

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
META_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"

# Refresh this many seconds before the recorded expiry, so a token that is
# about to lapse mid-request never gets handed out.
EXPIRY_SLACK_SECONDS = 60


def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.encode())


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Cannot decrypt stored OAuth token — TOKEN_ENCRYPTION_KEY changed "
            "since it was saved. Delete the connection and re-authorize."
        )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "account"


def _load() -> list[dict[str, Any]]:
    if CONNECTIONS_PATH.exists():
        try:
            data = json.loads(CONNECTIONS_PATH.read_text())
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save(connections: list[dict[str, Any]]) -> None:
    CONNECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONNECTIONS_PATH.write_text(json.dumps(connections, indent=2))


def _public(conn: dict[str, Any]) -> dict[str, Any]:
    """Copy safe for API responses — token ciphertext stripped."""
    return {k: v for k, v in conn.items() if k not in ("accessToken", "refreshToken")}


def save_connection(data: dict[str, Any]) -> dict[str, Any]:
    """Store a new connection (tokens arrive plaintext, stored encrypted).

    If a connection for the same provider + account already exists it is
    replaced in place (re-authorizing refreshes its tokens).
    """
    provider = (data.get("provider") or "").strip().lower()
    account = (data.get("accountEmailOrName") or "").strip()
    if provider not in ("google", "meta"):
        raise ValueError('provider must be "google" or "meta"')
    if not account:
        raise ValueError("accountEmailOrName is required")
    if not data.get("accessToken"):
        raise ValueError("accessToken is required")

    connections = _load()
    cid = f"{provider}-{_slugify(account)}"
    conn = {
        "id": cid,
        "provider": provider,
        "accountEmailOrName": account,
        "accessToken": _encrypt(data["accessToken"]),
        "refreshToken": _encrypt(data.get("refreshToken") or ""),
        "expiresAt": int(data.get("expiresAt") or 0),
        "scopes": (data.get("scopes") or "").strip(),
        "createdAt": int(time.time()),
    }

    existing = next((c for c in connections if c["id"] == cid), None)
    if existing:
        # Google only returns a refresh token on first consent; keep the old one.
        if not data.get("refreshToken") and existing.get("refreshToken"):
            conn["refreshToken"] = existing["refreshToken"]
        conn["createdAt"] = existing.get("createdAt", conn["createdAt"])
        connections[connections.index(existing)] = conn
    else:
        connections.append(conn)
    _save(connections)
    return _public(conn)


def get_connection(connection_id: str) -> dict[str, Any] | None:
    conn = next((c for c in _load() if c.get("id") == connection_id), None)
    return _public(conn) if conn else None


def list_connections() -> list[dict[str, Any]]:
    return [_public(c) for c in _load()]


def delete_connection(connection_id: str) -> bool:
    connections = _load()
    remaining = [c for c in connections if c["id"] != connection_id]
    if len(remaining) == len(connections):
        return False
    _save(remaining)
    return True


def get_valid_access_token(connection_id: str) -> str:
    """Return a plaintext access token, refreshing it first if expired."""
    connections = _load()
    conn = next((c for c in connections if c.get("id") == connection_id), None)
    if conn is None:
        raise KeyError(f"unknown connection: {connection_id}")

    expires_at = int(conn.get("expiresAt") or 0)
    if not expires_at or expires_at - EXPIRY_SLACK_SECONDS > time.time():
        return _decrypt(conn["accessToken"])

    if conn["provider"] == "google":
        _refresh_google(conn)
    else:
        _refresh_meta(conn)
    _save(connections)  # conn is mutated in place inside the loaded list
    return _decrypt(conn["accessToken"])


def get_refresh_token(connection_id: str) -> str:
    """Plaintext refresh token ("" if the provider issued none, e.g. Meta)."""
    conn = next((c for c in _load() if c.get("id") == connection_id), None)
    if conn is None:
        raise KeyError(f"unknown connection: {connection_id}")
    return _decrypt(conn.get("refreshToken") or "")


def _refresh_google(conn: dict[str, Any]) -> None:
    refresh_token = _decrypt(conn.get("refreshToken") or "")
    if not refresh_token:
        raise ValueError(
            f"connection {conn['id']} has no refresh token — re-authorize it"
        )
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    conn["accessToken"] = _encrypt(tok["access_token"])
    conn["expiresAt"] = int(time.time()) + int(tok.get("expires_in") or 3600)


def _refresh_meta(conn: dict[str, Any]) -> None:
    # Meta has no refresh tokens; exchange the current (long-lived) token for
    # a fresh long-lived one. Fails once the old token has fully expired.
    resp = httpx.get(
        META_TOKEN_URL,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": _decrypt(conn["accessToken"]),
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    conn["accessToken"] = _encrypt(tok["access_token"])
    conn["expiresAt"] = int(time.time()) + int(tok.get("expires_in") or 5184000)
