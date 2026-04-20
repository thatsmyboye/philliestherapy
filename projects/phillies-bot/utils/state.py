"""
Persist bot state (season highs, career highs/totals, milestones) to data/state.json.
"""
import json
import os
from pathlib import Path

STATE_PATH = Path(__file__).parent.parent / "data" / "state.json"

_DEFAULT_STATE = {
    "season_highs": {},
    "career_highs": {},
    "career_totals": {},
    "season_totals": {},
    "posted_milestones": [],
    "last_play_counts": {},
    # Steal monitor: per-runner attempt history for weighted success rate tracking
    # { player_id_str: { "name": str, "attempts": [ {success, difficulty, ...} ] } }
    "steal_grades": {},
    # Deduplication: set of "game_pk:play_idx:event_idx" strings already alerted
    "steal_events_posted": [],
    # Per-game event count tracking for steal monitor (more granular than last_play_counts)
    # { game_pk_str: { play_idx_str: event_count } }
    "steal_event_counts": {},
}


def load() -> dict:
    """Load state from Supabase; fall back to disk if unavailable."""
    from utils.supabase_db import kv_get
    remote = kv_get("bot_state")
    if remote is not None:
        for key, default in _DEFAULT_STATE.items():
            remote.setdefault(key, default.copy() if isinstance(default, dict) else list(default))
        return remote
    # File fallback
    if not STATE_PATH.exists():
        return {k: (v.copy() if isinstance(v, dict) else list(v)) for k, v in _DEFAULT_STATE.items()}
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
        for key, default in _DEFAULT_STATE.items():
            data.setdefault(key, default.copy() if isinstance(default, dict) else list(default))
        return data
    except (json.JSONDecodeError, OSError):
        return {k: (v.copy() if isinstance(v, dict) else list(v)) for k, v in _DEFAULT_STATE.items()}


def save(state: dict) -> None:
    """Persist state to Supabase (primary) and disk (backup)."""
    from utils.supabase_db import kv_set
    kv_set("bot_state", state)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(STATE_PATH) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def get_season_high(state: dict, player_id: str, stat: str) -> float:
    return state["season_highs"].get(str(player_id), {}).get(stat, 0.0)


def set_season_high(state: dict, player_id: str, stat: str, value: float) -> None:
    pid = str(player_id)
    state["season_highs"].setdefault(pid, {})[stat] = value


def get_career_high(state: dict, player_id: str, stat: str) -> float:
    return state["career_highs"].get(str(player_id), {}).get(stat, 0.0)


def set_career_high(state: dict, player_id: str, stat: str, value: float) -> None:
    pid = str(player_id)
    state["career_highs"].setdefault(pid, {})[stat] = value


def get_career_total(state: dict, player_id: str, stat: str) -> int:
    return state["career_totals"].get(str(player_id), {}).get(stat, 0)


def set_career_total(state: dict, player_id: str, stat: str, value: int) -> None:
    pid = str(player_id)
    state["career_totals"].setdefault(pid, {})[stat] = value


def get_season_total(state: dict, player_id: str, stat: str) -> int:
    return state["season_totals"].get(str(player_id), {}).get(stat, 0)


def set_season_total(state: dict, player_id: str, stat: str, value: int) -> None:
    pid = str(player_id)
    state["season_totals"].setdefault(pid, {})[stat] = value


def milestone_key(player_id: str, stat: str, value: int) -> str:
    return f"{player_id}_{stat}_{value}"


def has_milestone(state: dict, player_id: str, stat: str, value: int) -> bool:
    return milestone_key(player_id, stat, value) in state["posted_milestones"]


def record_milestone(state: dict, player_id: str, stat: str, value: int) -> None:
    key = milestone_key(player_id, stat, value)
    if key not in state["posted_milestones"]:
        state["posted_milestones"].append(key)


# ---------------------------------------------------------------------------
# Steal grades helpers
# ---------------------------------------------------------------------------

def add_steal_attempt(state: dict, player_id: int, name: str, attempt: dict) -> None:
    """
    Record a steal attempt for a runner.

    attempt dict fields:
      success (bool), difficulty (float), base (str), date (str),
      game_pk (int), pitcher_name (str), catcher_name (str),
      pitch_type (str|None), pitch_speed (float|None),
      pop_time (float|None), sprint_speed (float|None)
    """
    pid = str(player_id)
    if pid not in state["steal_grades"]:
        state["steal_grades"][pid] = {"name": name, "attempts": []}
    entry = state["steal_grades"][pid]
    # Keep name current (roster moves)
    entry["name"] = name
    entry["attempts"].append(attempt)


def get_steal_grades(state: dict) -> dict:
    """Return the full steal_grades dict keyed by player_id string."""
    return state.get("steal_grades", {})


def has_steal_event_posted(state: dict, fingerprint: str) -> bool:
    return fingerprint in state.get("steal_events_posted", [])


def record_steal_event_posted(state: dict, fingerprint: str) -> None:
    posted = state.setdefault("steal_events_posted", [])
    if fingerprint not in posted:
        posted.append(fingerprint)
    # Prune to last 1000 to prevent unbounded growth
    if len(posted) > 1000:
        state["steal_events_posted"] = posted[-1000:]
