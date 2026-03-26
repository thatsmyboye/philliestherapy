"""
Persistence layer for the live stat props system.

Manages data/props.json with atomic writes to avoid corruption.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

PROPS_PATH = Path(__file__).parent.parent.parent / "data" / "props.json"

_DEFAULT: dict = {
    "props": [],
    "scoreboard_message_id": None,
    "alerts_posted": [],
}


class PropsStore:
    """Thin wrapper around props.json with atomic saves."""

    def __init__(self) -> None:
        self._data = self._load()

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if PROPS_PATH.exists():
            try:
                with open(PROPS_PATH) as f:
                    data = json.load(f)
                for k, v in _DEFAULT.items():
                    data.setdefault(k, type(v)() if isinstance(v, (list, dict)) else v)
                return data
            except Exception:
                pass
        return {k: (type(v)() if isinstance(v, (list, dict)) else v) for k, v in _DEFAULT.items()}

    def save(self) -> None:
        PROPS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(PROPS_PATH) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, str(PROPS_PATH))

    # ── Props CRUD ────────────────────────────────────────────────────────────

    @property
    def props(self) -> list[dict]:
        return self._data["props"]

    def add_prop(self, prop: dict) -> None:
        self._data["props"].append(prop)
        self.save()

    def remove_prop(self, prop_id: str) -> bool:
        before = len(self._data["props"])
        self._data["props"] = [p for p in self._data["props"] if p["id"] != prop_id]
        changed = len(self._data["props"]) < before
        if changed:
            self.save()
        return changed

    def clear_props(self) -> None:
        self._data["props"] = []
        self._data["alerts_posted"] = []
        self._data["scoreboard_message_id"] = None
        self.save()

    # ── Scoreboard message ID ─────────────────────────────────────────────────

    @property
    def scoreboard_message_id(self) -> Optional[int]:
        mid = self._data.get("scoreboard_message_id")
        return int(mid) if mid else None

    @scoreboard_message_id.setter
    def scoreboard_message_id(self, value: Optional[int]) -> None:
        self._data["scoreboard_message_id"] = value
        self.save()

    # ── Alert deduplication ──────────────────────────────────────────────────

    def has_alert_posted(self, fingerprint: str) -> bool:
        return fingerprint in self._data.get("alerts_posted", [])

    def record_alert_posted(self, fingerprint: str) -> None:
        posted: list = self._data.setdefault("alerts_posted", [])
        if fingerprint not in posted:
            posted.append(fingerprint)
        if len(posted) > 500:
            self._data["alerts_posted"] = posted[-500:]
        self.save()
