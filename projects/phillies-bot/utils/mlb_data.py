"""
MLB data helpers: pybaseball Statcast queries and statsapi wrappers,
with simple in-memory TTL caching to avoid hammering the data sources.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
import statsapi
from pybaseball import statcast_batter, statcast_pitcher

# ---------------------------------------------------------------------------
# Pitch type code → friendly label
# ---------------------------------------------------------------------------
PITCH_TYPE_LABELS: dict[str, str] = {
    "FF": "Four-Seam Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "CU": "Curveball",
    "CH": "Changeup",
    "FS": "Splitter",
    "KC": "Knuckle-Curve",
    "ST": "Sweeper",
    "SV": "Slurve",
    "KN": "Knuckleball",
}

# Inverse map: label → code (for slash command choice resolution)
PITCH_LABEL_TO_CODE: dict[str, str] = {v: k for k, v in PITCH_TYPE_LABELS.items()}

# Phillies MLBAM team ID
PHILLIES_TEAM_ID = 143

# Season start — update this each year or derive dynamically
CURRENT_SEASON = datetime.now().year
SEASON_START = f"{CURRENT_SEASON}-03-01"

# ---------------------------------------------------------------------------
# Simple TTL cache
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < ttl_seconds:
            return val
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Statcast helpers
# ---------------------------------------------------------------------------

def get_pitcher_statcast(mlbam_id: int) -> Optional[pd.DataFrame]:
    """Return this-season Statcast data for a pitcher (4-hour cache)."""
    key = f"pitcher_{mlbam_id}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    try:
        df = statcast_pitcher(SEASON_START, today, player_id=mlbam_id)
        _cache_set(key, df)
        return df
    except Exception:
        return None


def get_batter_statcast(mlbam_id: int) -> Optional[pd.DataFrame]:
    """Return this-season Statcast data for a batter (4-hour cache)."""
    key = f"batter_{mlbam_id}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    try:
        df = statcast_batter(SEASON_START, today, player_id=mlbam_id)
        _cache_set(key, df)
        return df
    except Exception:
        return None


def top_pitch_velos(mlbam_id: int, pitch_code: str, n: int = 3) -> list[dict]:
    """
    Return the n fastest pitches of a given type for a pitcher this season.

    Each dict contains: speed, date, opponent, pitch_type_label, count_str.
    """
    df = get_pitcher_statcast(mlbam_id)
    if df is None or df.empty:
        return []

    df = df[df["pitch_type"] == pitch_code].copy()
    df = df.dropna(subset=["release_speed"])
    df = df.sort_values("release_speed", ascending=False).head(n)

    results = []
    for _, row in df.iterrows():
        results.append({
            "speed": round(float(row["release_speed"]), 1),
            "date": str(row.get("game_date", ""))[:10],
            "pitch_type_label": PITCH_TYPE_LABELS.get(pitch_code, pitch_code),
            "balls": int(row.get("balls", 0)),
            "strikes": int(row.get("strikes", 0)),
            "inning": int(row.get("inning", 0)),
            "description": str(row.get("description", "")),
        })
    return results


def top_exit_velos(mlbam_id: int, n: int = 3) -> list[dict]:
    """
    Return the n hardest-hit balls in play (including HRs) for a batter this season.

    Each dict contains: exit_velo, launch_angle, event, date.
    """
    df = get_batter_statcast(mlbam_id)
    if df is None or df.empty:
        return []

    df = df.dropna(subset=["launch_speed"]).copy()
    df = df.sort_values("launch_speed", ascending=False).head(n)

    results = []
    for _, row in df.iterrows():
        event = str(row.get("events", "unknown")).replace("_", " ").title()
        results.append({
            "exit_velo": round(float(row["launch_speed"]), 1),
            "launch_angle": round(float(row.get("launch_angle", 0)), 1),
            "hit_distance": int(row.get("hit_distance_sc", 0) or 0),
            "event": event,
            "date": str(row.get("game_date", ""))[:10],
        })
    return results


# ---------------------------------------------------------------------------
# Luck / unluck helpers
# ---------------------------------------------------------------------------

def _hitter_luck_score(df: pd.DataFrame, lucky: bool) -> float:
    """
    lucky=True  → hits on low-xBA events (sum of 1 - xBA per hit)
    lucky=False → outs on high-xBA events (sum of xBA per out)
    """
    xba_col = "estimated_ba_using_speedangle"
    if xba_col not in df.columns:
        return 0.0
    df = df.dropna(subset=[xba_col])
    is_hit = df["events"].isin(["single", "double", "triple", "home_run"])
    if lucky:
        lucky_hits = df[is_hit & (df[xba_col] < 0.250)]
        return float((1 - lucky_hits[xba_col]).sum())
    else:
        unlucky_outs = df[~is_hit & df["events"].notna() & (df[xba_col] > 0.500)]
        return float(unlucky_outs[xba_col].sum())


def _pitcher_luck_score(df: pd.DataFrame, lucky: bool) -> float:
    """
    lucky=True  → outs on high-xBA events (pitcher got lucky)
    lucky=False → hits on low-xBA events (pitcher was unlucky)
    """
    xba_col = "estimated_ba_using_speedangle"
    if xba_col not in df.columns:
        return 0.0
    df = df.dropna(subset=[xba_col])
    is_hit = df["events"].isin(["single", "double", "triple", "home_run"])
    if lucky:
        lucky_outs = df[~is_hit & df["events"].notna() & (df[xba_col] > 0.500)]
        return float(lucky_outs[xba_col].sum())
    else:
        unlucky_hits = df[is_hit & (df[xba_col] < 0.250)]
        return float((1 - unlucky_hits[xba_col]).sum())


def get_phillies_luck(lucky: bool) -> dict[str, list[dict]]:
    """
    Return {'hitters': [...], 'pitchers': [...]} with top-3 luckiest or unluckiest
    Phillies players.

    Each entry: {'name': str, 'score': float, 'player_id': int}.
    """
    roster = get_phillies_roster()
    hitter_scores: list[dict] = []
    pitcher_scores: list[dict] = []

    for player in roster:
        pid = player["id"]
        name = player["fullName"]
        pos = player.get("primaryPosition", {}).get("abbreviation", "")
        is_pitcher = pos == "P"

        if is_pitcher:
            df = get_pitcher_statcast(pid)
            if df is None or df.empty:
                continue
            score = _pitcher_luck_score(df, lucky)
            if score > 0:
                pitcher_scores.append({"name": name, "score": round(score, 2), "player_id": pid})
        else:
            df = get_batter_statcast(pid)
            if df is None or df.empty:
                continue
            score = _hitter_luck_score(df, lucky)
            if score > 0:
                hitter_scores.append({"name": name, "score": round(score, 2), "player_id": pid})

    hitter_scores.sort(key=lambda x: x["score"], reverse=True)
    pitcher_scores.sort(key=lambda x: x["score"], reverse=True)
    return {"hitters": hitter_scores[:3], "pitchers": pitcher_scores[:3]}


# ---------------------------------------------------------------------------
# Roster helper
# ---------------------------------------------------------------------------

def get_phillies_roster() -> list[dict]:
    """Return the current Phillies active roster (24-hour cache)."""
    key = f"roster_{CURRENT_SEASON}"
    cached = _cache_get(key, 24 * 3600)
    if cached is not None:
        return cached

    try:
        data = statsapi.get(
            "sports_players",
            {"sportId": 1, "season": CURRENT_SEASON, "gameType": "R"},
        )
        players = [
            p for p in data.get("people", [])
            if p.get("currentTeam", {}).get("id") == PHILLIES_TEAM_ID
        ]
        _cache_set(key, players)
        return players
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Career / season stats via statsapi
# ---------------------------------------------------------------------------

def get_career_stats(player_id: int) -> dict:
    """
    Return career cumulative hitting and pitching stats.
    Result: {'hitting': {...}, 'pitching': {...}}
    """
    try:
        data = statsapi.player_stat_data(
            player_id,
            group="[hitting,pitching]",
            type="career",
        )
        result = {}
        for group in data.get("stats", []):
            group_name = group.get("group", {}).get("displayName", "").lower()
            stats = group.get("stats", {})
            result[group_name] = stats
        return result
    except Exception:
        return {}


def get_season_stats_by_year(player_id: int) -> list[dict]:
    """
    Return season-by-season hitting stats to check 100+ PA eligibility
    and to seed career high tracking.
    """
    try:
        data = statsapi.player_stat_data(
            player_id,
            group="[hitting,pitching]",
            type="yearByYear",
        )
        seasons = []
        for group in data.get("stats", []):
            group_name = group.get("group", {}).get("displayName", "").lower()
            for season_entry in group.get("splits", []):
                entry = dict(season_entry.get("stat", {}))
                entry["season"] = season_entry.get("season", "")
                entry["group"] = group_name
                seasons.append(entry)
        return seasons
    except Exception:
        return []


def get_live_game_data(game_pk: int) -> Optional[dict]:
    """Return live game data dict from statsapi (no cache)."""
    try:
        return statsapi.get("game", {"gamePk": game_pk})
    except Exception:
        return None


def get_todays_phillies_games() -> list[dict]:
    """Return today's Phillies games from the schedule."""
    try:
        today = date.today().strftime("%Y-%m-%d")
        return statsapi.schedule(date=today, team=PHILLIES_TEAM_ID)
    except Exception:
        return []
