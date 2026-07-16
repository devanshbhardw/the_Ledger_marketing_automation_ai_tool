"""Thin Redis cache helper for report responses."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import redis

from .config import settings

_client: Optional[redis.Redis] = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def make_key(report: str, property_id: str, start: str, end: str, sig: str = "") -> str:
    # `sig` is a hash of the report definition so a def change (new dimension,
    # metric, filter, …) yields a new key and stale entries are bypassed.
    raw = f"{report}:{property_id}:{start}:{end}:{sig}"
    return "ttk:report:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def get(key: str) -> Optional[dict[str, Any]]:
    try:
        raw = client().get(key)
        return json.loads(raw) if raw else None
    except (redis.RedisError, json.JSONDecodeError):
        return None


def set(key: str, value: dict[str, Any], ttl: Optional[int] = None) -> None:
    try:
        client().set(key, json.dumps(value), ex=ttl or settings.cache_ttl_seconds)
    except redis.RedisError:
        pass  # cache is best-effort; never fail a request on cache error
