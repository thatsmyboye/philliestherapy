"""
Redis-backed TTL cache with in-memory fallback.

Stores values as JSON with a timestamp so the caller's TTL logic is preserved
exactly. Falls back to a plain in-memory dict when REDIS_URL is not set or
Redis is unreachable.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

# In-memory fallback store: key -> (timestamp, value)
_mem: dict[str, tuple[float, Any]] = {}

_client = None
_client_checked = False


def _redis():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis as _r
        r = _r.from_url(url, decode_responses=True)
        r.ping()
        _client = r
    except Exception:
        _client = None
    return _client


def _key(k: str) -> str:
    return f"phillies:{k}"


def cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    """Return cached value if it exists and is within TTL, else None."""
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_key(key))
            if raw is not None:
                entry = json.loads(raw)
                if time.time() - entry["ts"] < ttl_seconds:
                    return entry["val"]
                r.delete(_key(key))
                return None
        except Exception:
            pass
    # in-memory fallback
    if key in _mem:
        ts, val = _mem[key]
        if time.time() - ts < ttl_seconds:
            return val
    return None


def cache_set(key: str, value: Any) -> None:
    """Store value with current timestamp. Redis TTL is 24 h for cleanup."""
    ts = time.time()
    r = _redis()
    if r is not None:
        try:
            payload = json.dumps({"ts": ts, "val": value}, default=str)
            r.set(_key(key), payload, ex=86400)
            return
        except Exception:
            pass
    _mem[key] = (ts, value)
