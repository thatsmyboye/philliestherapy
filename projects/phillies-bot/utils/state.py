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
}


def load() -> dict:
    """Load state from disk; return defaults if file is missing or malformed."""
    if not STATE_PATH.exists():
        return {k: (v.copy() if isinstance(v, dict) else list(v)) for k, v in _DEFAULT_STATE.items()}
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
        # Ensure all top-level keys exist
        for key, default in _DEFAULT_STATE.items():
            data.setdefault(key, default.copy() if isinstance(default, dict) else list(default))
        return data
    except (json.JSONDecodeError, OSError):
        return {k: (v.copy() if isinstance(v, dict) else list(v)) for k, v in _DEFAULT_STATE.items()}


def save(state: dict) -> None:
    """Persist state to disk atomically."""
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
