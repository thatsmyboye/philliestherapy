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
from pybaseball import statcast as statcast_range, statcast_batter, statcast_pitcher

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

# Season configuration
# Spring Training data is targeted until March 24; Regular Season begins March 25.
CURRENT_SEASON = datetime.now().year
SPRING_TRAINING_START = f"{CURRENT_SEASON}-03-01"
REGULAR_SEASON_START = f"{CURRENT_SEASON}-03-25"


def is_spring_training() -> bool:
    """Return True if today is before the regular season start (March 25)."""
    return date.today() < date(date.today().year, 3, 25)


def get_season_start() -> str:
    """Return the appropriate Statcast query start date based on today's date."""
    return SPRING_TRAINING_START if is_spring_training() else REGULAR_SEASON_START


def get_game_type() -> str:
    """Return 'S' (spring training) or 'R' (regular season) based on today's date."""
    return "S" if is_spring_training() else "R"


# Module-level alias kept for any external imports; prefer get_season_start() for
# runtime-accurate values when the bot runs across the season boundary.
SEASON_START = SPRING_TRAINING_START

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
        df = statcast_pitcher(get_season_start(), today, player_id=mlbam_id)
        if df is not None and not df.empty and "game_type" in df.columns:
            df = df[df["game_type"] == get_game_type()].copy()
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
        df = statcast_batter(get_season_start(), today, player_id=mlbam_id)
        if df is not None and not df.empty and "game_type" in df.columns:
            df = df[df["game_type"] == get_game_type()].copy()
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


def _get_phillies_team_statcast() -> Optional[pd.DataFrame]:
    """
    Fetch all Phillies batted-ball events this season in one bulk call (4-hour cache).
    This is significantly faster than looping over each player individually.
    """
    key = f"team_statcast_PHI_{CURRENT_SEASON}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    try:
        df = statcast_range(get_season_start(), today, team="PHI")
        if df is not None and not df.empty and "game_type" in df.columns:
            df = df[df["game_type"] == get_game_type()].copy()
        _cache_set(key, df)
        return df
    except Exception:
        return None


def get_phillies_luck(lucky: bool) -> dict[str, list[dict]]:
    """
    Return {'hitters': [...], 'pitchers': [...]} with top-3 luckiest or unluckiest
    Phillies players.

    Uses a single bulk team Statcast pull rather than per-player queries.
    Each entry: {'name': str, 'score': float, 'player_id': int}.
    """
    roster = get_phillies_roster()
    # Build quick lookup: player_id → name and role
    player_info = {
        p["id"]: {
            "name": p["fullName"],
            "is_pitcher": p.get("primaryPosition", {}).get("abbreviation", "") == "P",
        }
        for p in roster
    }
    phillies_ids = set(player_info.keys())

    df = _get_phillies_team_statcast()
    hitter_scores: list[dict] = []
    pitcher_scores: list[dict] = []

    if df is not None and not df.empty:
        # --- Hitters (Phillies players as batter) ---
        batter_df = df[df["batter"].isin(phillies_ids)].copy()
        for pid, grp in batter_df.groupby("batter"):
            info = player_info.get(int(pid))
            if info is None or info["is_pitcher"]:
                continue
            score = _hitter_luck_score(grp, lucky)
            if score > 0:
                hitter_scores.append({"name": info["name"], "score": round(score, 2), "player_id": int(pid)})

        # --- Pitchers (Phillies players as pitcher) ---
        pitcher_df = df[df["pitcher"].isin(phillies_ids)].copy()
        for pid, grp in pitcher_df.groupby("pitcher"):
            info = player_info.get(int(pid))
            if info is None or not info["is_pitcher"]:
                continue
            score = _pitcher_luck_score(grp, lucky)
            if score > 0:
                pitcher_scores.append({"name": info["name"], "score": round(score, 2), "player_id": int(pid)})

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
            {"sportId": 1, "season": CURRENT_SEASON, "gameType": get_game_type()},
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


# ---------------------------------------------------------------------------
# Standings helpers
# ---------------------------------------------------------------------------

DIVISION_IDS: dict[str, int] = {
    "NL East": 204,
    "NL Central": 205,
    "NL West": 206,
    "AL East": 201,
    "AL Central": 202,
    "AL West": 203,
}


def get_team_abbreviations() -> dict[int, str]:
    """Return a mapping of MLBAM team ID → abbreviation (24-hour cache)."""
    key = "team_abbreviations"
    cached = _cache_get(key, 24 * 3600)
    if cached is not None:
        return cached
    try:
        data = statsapi.get("teams", {"sportId": 1})
        abbr_map = {
            t["id"]: t.get("abbreviation", t["name"][:3].upper())
            for t in data.get("teams", [])
        }
        _cache_set(key, abbr_map)
        return abbr_map
    except Exception:
        return {}


def _pythag_pct(runs_scored: int, runs_allowed: int) -> Optional[float]:
    """Return Pythagorean winning percentage using exponent 1.83."""
    if runs_scored == 0 and runs_allowed == 0:
        return None
    try:
        rs = runs_scored ** 1.83
        ra = runs_allowed ** 1.83
        return rs / (rs + ra)
    except Exception:
        return None


def _parse_team_record(tr: dict, abbr_map: dict[int, str], use_wc_gb: bool = False) -> dict:
    """Parse a single teamRecord dict from the standings API response."""
    team_id = tr.get("team", {}).get("id", 0)
    team_name = tr.get("team", {}).get("name", "Unknown")
    abbr = abbr_map.get(team_id, team_name[:3].upper())

    wins = tr.get("wins", 0)
    losses = tr.get("losses", 0)
    pct = tr.get("pct", ".000")

    if use_wc_gb:
        gb = tr.get("wildCardGamesBack", tr.get("gamesBack", "-"))
    else:
        gb = tr.get("gamesBack", "-")
    if gb == "0.0":
        gb = "-"

    runs_scored = tr.get("runsScored", 0) or 0
    runs_allowed = tr.get("runsAllowed", 0) or 0
    pythag = _pythag_pct(int(runs_scored), int(runs_allowed))

    return {
        "abbr": abbr,
        "name": team_name,
        "team_id": team_id,
        "w": int(wins),
        "l": int(losses),
        "pct": pct,
        "gb": gb,
        "pythag": pythag,
    }


def _fetch_standings_data(standings_type: str) -> Optional[dict]:
    """Fetch raw standings data from the MLB API (5-minute cache per type)."""
    key = f"standings_{standings_type}_{CURRENT_SEASON}"
    cached = _cache_get(key, 5 * 60)
    if cached is not None:
        return cached
    try:
        data = statsapi.get(
            "standings",
            {
                "leagueId": "103,104",
                "season": CURRENT_SEASON,
                "standingsTypes": standings_type,
            },
        )
        _cache_set(key, data)
        return data
    except Exception:
        return None


def get_division_standings(division_name: str) -> list[dict]:
    """
    Return sorted team records for the given division name.

    Each dict: abbr, name, team_id, w, l, pct, gb, pythag.
    """
    division_id = DIVISION_IDS.get(division_name)
    if not division_id:
        return []

    data = _fetch_standings_data("regularSeason")
    if not data:
        return []

    abbr_map = get_team_abbreviations()
    for record in data.get("records", []):
        if record.get("division", {}).get("id") == division_id:
            return [
                _parse_team_record(tr, abbr_map)
                for tr in record.get("teamRecords", [])
            ]
    return []


def get_wildcard_standings() -> dict[str, list[dict]]:
    """
    Return wild card standings for both AL and NL.

    Result: {'AL': [...teams...], 'NL': [...teams...]}
    Each team dict: abbr, name, team_id, w, l, pct, gb, pythag.
    """
    data = _fetch_standings_data("wildCard")
    if not data:
        return {"AL": [], "NL": []}

    abbr_map = get_team_abbreviations()
    result: dict[str, list[dict]] = {"AL": [], "NL": []}

    for record in data.get("records", []):
        league_id = record.get("league", {}).get("id")
        if league_id == 103:
            league_key = "AL"
        elif league_id == 104:
            league_key = "NL"
        else:
            continue
        teams = [
            _parse_team_record(tr, abbr_map, use_wc_gb=True)
            for tr in record.get("teamRecords", [])
        ]
        result[league_key].extend(teams)

    return result
