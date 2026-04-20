"""
Supabase client and key-value persistence helpers.

Requires SUPABASE_URL and SUPABASE_KEY (service_role key) env vars.
All operations are no-ops when credentials are absent so the bot
degrades gracefully to file-based storage.
"""
from __future__ import annotations

import os
from typing import Any, Optional

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
    except Exception:
        _client = None
    return _client


def kv_get(key: str) -> Optional[Any]:
    """Return the JSONB value stored under *key*, or None."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = (
            client.table("kv_store")
            .select("value")
            .eq("key", key)
            .execute()
        )
        if result.data:
            return result.data[0]["value"]
        return None
    except Exception:
        return None


def kv_set(key: str, value: Any) -> None:
    """Upsert *value* (must be JSON-serialisable) under *key*."""
    client = _get_client()
    if client is None:
        return
    try:
        client.table("kv_store").upsert({"key": key, "value": value}).execute()
    except Exception:
        pass
