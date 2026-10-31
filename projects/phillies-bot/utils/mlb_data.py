"""
MLB data helpers: Baseball Savant Statcast queries (direct CSV) and statsapi
wrappers, with simple in-memory TTL caching to avoid hammering the data sources.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import statsapi

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

# Season configuration — kept as module-level constants for external imports,
# but URL construction and date helpers always use date.today().year at call
# time so the bot remains correct across year boundaries without a restart.
CURRENT_SEASON = datetime.now().year
SPRING_TRAINING_START = f"{CURRENT_SEASON}-03-01"
REGULAR_SEASON_START = f"{CURRENT_SEASON}-03-25"


def _current_year() -> int:
    """Return the current calendar year at call time (never stale)."""
    return date.today().year


def is_spring_training() -> bool:
    """Return True if today is before the regular season start (March 25)."""
    return date.today() < date(date.today().year, 3, 25)


def get_season_start() -> str:
    """Return the appropriate Statcast query start date based on today's date."""
    year = _current_year()
    if is_spring_training():
        return f"{year}-03-01"
    return f"{year}-03-25"


def get_game_type() -> str:
    """Return 'S' (spring training) or 'R' (regular season) based on today's date."""
    return "S" if is_spring_training() else "R"


def is_early_regular_season(days: int = 28) -> bool:
    """
    Return True if today is within `days` days after the regular season start.
    The default window is 28 days (first full month) — cross-divisional matchup
    history and per-pitch-type samples are too sparse before that threshold.
    """
    from datetime import timedelta
    reg_start = date(date.today().year, 3, 25)
    return reg_start <= date.today() < reg_start + timedelta(days=days)


# Module-level alias kept for any external imports; prefer get_season_start() for
# runtime-accurate values when the bot runs across the season boundary.
SEASON_START = SPRING_TRAINING_START

# ---------------------------------------------------------------------------
# TTL cache (Redis-backed with in-memory fallback)
# ---------------------------------------------------------------------------
from utils.redis_cache import cache_get as _cache_get, cache_set as _cache_set


# ---------------------------------------------------------------------------
# Baseball Savant CSV helper
# ---------------------------------------------------------------------------

_SAVANT_BASE = "https://baseballsavant.mlb.com/statcast_search/csv"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PhilliesBot/1.0)"}


def _to_float(val: Any) -> Optional[float]:
    """Safely convert a CSV field to float, returning None on failure."""
    try:
        s = str(val).strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> int:
    """Safely convert a CSV field to int, returning 0 on failure."""
    try:
        s = str(val).strip()
        return int(float(s)) if s else 0
    except (ValueError, TypeError):
        return 0


def _fetch_statcast_csv(url: str) -> list[dict]:
    """
    GET a Baseball Savant CSV URL and return rows as a list of dicts.
    Returns an empty list on any error or if the response isn't CSV data.
    """
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
        # Baseball Savant returns HTML when there's an error or no results
        stripped = raw.strip()
        if not stripped or stripped.startswith("<"):
            return []
        reader = csv.DictReader(io.StringIO(stripped))
        return [row for row in reader]
    except Exception:
        return []


def _statcast_pitcher_url(mlbam_id: int, start: str, end: str, game_type: str) -> str:
    season = _current_year()
    return (
        f"{_SAVANT_BASE}?player_type=pitcher"
        f"&pitchers_lookup%5B%5D={mlbam_id}"
        f"&game_date_gt={start}&game_date_lt={end}"
        f"&hfGT={game_type}%7C&hfSea={season}%7C"
        f"&type=details&all=true"
    )


def _statcast_batter_url(mlbam_id: int, start: str, end: str, game_type: str) -> str:
    season = _current_year()
    return (
        f"{_SAVANT_BASE}?player_type=batter"
        f"&batters_lookup%5B%5D={mlbam_id}"
        f"&game_date_gt={start}&game_date_lt={end}"
        f"&hfGT={game_type}%7C&hfSea={season}%7C"
        f"&type=details&all=true"
    )


def _statcast_team_url(
    team: str, player_type: str, start: str, end: str, game_type: str
) -> str:
    season = _current_year()
    return (
        f"{_SAVANT_BASE}?player_type={player_type}"
        f"&team={team}"
        f"&game_date_gt={start}&game_date_lt={end}"
        f"&hfGT={game_type}%7C&hfSea={season}%7C"
        f"&type=details&all=true"
    )


# ---------------------------------------------------------------------------
# Statcast helpers
# ---------------------------------------------------------------------------

def get_pitcher_statcast(mlbam_id: int) -> list[dict]:
    """Return this-season Statcast rows for a pitcher (4-hour cache)."""
    key = f"pitcher_{mlbam_id}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    url = _statcast_pitcher_url(mlbam_id, get_season_start(), today, get_game_type())
    rows = _fetch_statcast_csv(url)
    result = [r for r in rows if r.get("game_type") == get_game_type()]
    _cache_set(key, result)
    return result


def get_batter_statcast(mlbam_id: int) -> list[dict]:
    """Return this-season Statcast rows for a batter (4-hour cache)."""
    key = f"batter_{mlbam_id}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    url = _statcast_batter_url(mlbam_id, get_season_start(), today, get_game_type())
    rows = _fetch_statcast_csv(url)
    result = [r for r in rows if r.get("game_type") == get_game_type()]
    _cache_set(key, result)
    return result


def top_pitch_velos(mlbam_id: int, pitch_code: str, n: int = 3) -> list[dict]:
    """
    Return the n fastest pitches of a given type for a pitcher this season.

    Each dict contains: speed, date, opponent, pitch_type_label, count_str.
    """
    rows = get_pitcher_statcast(mlbam_id)
    if not rows:
        return []

    filtered = [
        r for r in rows
        if r.get("pitch_type") == pitch_code and _to_float(r.get("release_speed")) is not None
    ]
    filtered.sort(key=lambda r: _to_float(r.get("release_speed")) or 0.0, reverse=True)
    filtered = filtered[:n]

    results = []
    for row in filtered:
        results.append({
            "speed": round(_to_float(row.get("release_speed")) or 0.0, 1),
            "date": str(row.get("game_date", ""))[:10],
            "pitch_type_label": PITCH_TYPE_LABELS.get(pitch_code, pitch_code),
            "balls": _to_int(row.get("balls")),
            "strikes": _to_int(row.get("strikes")),
            "inning": _to_int(row.get("inning")),
            "description": str(row.get("description", "")),
        })
    return results


def top_exit_velos(mlbam_id: int, n: int = 3) -> list[dict]:
    """
    Return the n hardest-hit balls in play (including HRs) for a batter this season.

    Each dict contains: exit_velo, launch_angle, event, date.
    """
    rows = get_batter_statcast(mlbam_id)
    if not rows:
        return []

    filtered = [r for r in rows if _to_float(r.get("launch_speed")) is not None]
    filtered.sort(key=lambda r: _to_float(r.get("launch_speed")) or 0.0, reverse=True)
    filtered = filtered[:n]

    results = []
    for row in filtered:
        event = str(row.get("events", "unknown")).replace("_", " ").title()
        dist = _to_int(row.get("hit_distance_sc"))
        results.append({
            "exit_velo": round(_to_float(row.get("launch_speed")) or 0.0, 1),
            "launch_angle": round(_to_float(row.get("launch_angle")) or 0.0, 1),
            "hit_distance": dist,
            "event": event,
            "date": str(row.get("game_date", ""))[:10],
        })
    return results


# ---------------------------------------------------------------------------
# Luck / unluck helpers
# ---------------------------------------------------------------------------

_HIT_EVENTS = {"single", "double", "triple", "home_run"}


def _hitter_luck_score(rows: list[dict]) -> float:
    """
    Combined net hits added for a hitter:
      +  hits on low-xBA events  (sum of 1 - xBA per lucky hit)
      -  outs on high-xBA events (sum of xBA per unlucky out)
    Positive = net lucky, negative = net unlucky.
    """
    total = 0.0
    for row in rows:
        xba = _to_float(row.get("estimated_ba_using_speedangle"))
        if xba is None:
            continue
        is_hit = row.get("events", "") in _HIT_EVENTS
        if is_hit and xba < 0.250:
            total += 1 - xba
        elif not is_hit and row.get("events", "") and xba > 0.500:
            total -= xba
    return total


def _pitcher_luck_score(rows: list[dict]) -> float:
    """
    Combined net hits saved for a pitcher:
      +  outs on high-xBA events (sum of xBA per lucky out / hit saved)
      -  hits on low-xBA events  (sum of 1 - xBA per unlucky hit allowed)
    Positive = net lucky, negative = net unlucky.
    """
    total = 0.0
    for row in rows:
        xba = _to_float(row.get("estimated_ba_using_speedangle"))
        if xba is None:
            continue
        is_hit = row.get("events", "") in _HIT_EVENTS
        if not is_hit and row.get("events", "") and xba > 0.500:
            total += xba
        elif is_hit and xba < 0.250:
            total -= 1 - xba
    return total


def _get_phillies_batter_statcast() -> list[dict]:
    """Fetch all Phillies batter Statcast events this season (4-hour cache)."""
    key = f"team_batter_statcast_PHI_{_current_year()}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    url = _statcast_team_url("PHI", "batter", get_season_start(), today, get_game_type())
    rows = _fetch_statcast_csv(url)
    result = [r for r in rows if r.get("game_type") == get_game_type()]
    _cache_set(key, result)
    return result


def _get_phillies_pitcher_statcast() -> list[dict]:
    """Fetch all Phillies pitcher Statcast events this season (4-hour cache)."""
    return get_team_pitcher_statcast("PHI")


def get_team_pitcher_statcast(team_abbr: str) -> list[dict]:
    """
    Fetch all pitcher Statcast events for any team this season (4-hour cache).

    Uses the team-level Baseball Savant URL (proven reliable) rather than the
    individual-player pitchers_lookup[] endpoint, which can fail silently.

    team_abbr: Baseball Savant team abbreviation, e.g. "PHI", "COL", "NYM".
    """
    year = _current_year()
    key = f"team_pitcher_statcast_{team_abbr}_{year}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    url = _statcast_team_url(team_abbr, "pitcher", get_season_start(), today, get_game_type())
    rows = _fetch_statcast_csv(url)
    result = [r for r in rows if r.get("game_type") == get_game_type()]
    _cache_set(key, result)
    return result


def get_pitcher_statcast_multiyear(mlbam_id: int, prior_years: int = 2) -> list[dict]:
    """
    Return Statcast rows for a pitcher spanning the current season plus the
    previous `prior_years` regular seasons.  Used as a fallback when current-
    season cross-divisional matchup history is too sparse (early in the year).

    Rows from prior seasons carry a synthetic ``_season`` key so callers can
    label them accordingly.  Current-season rows reuse the standard
    ``get_pitcher_statcast()`` cache where possible.

    Results are cached for 6 hours under a per-pitcher, per-year key.
    """
    current = _current_year()
    key = f"pitcher_multiyear_{mlbam_id}_{current}"
    cached = _cache_get(key, 6 * 3600)
    if cached is not None:
        return cached

    all_rows: list[dict] = []

    # Fetch each prior regular season independently
    for yr in range(current - prior_years, current):
        url = _statcast_pitcher_url(
            mlbam_id,
            f"{yr}-03-20",
            f"{yr}-11-05",
            "R",
        )
        rows = _fetch_statcast_csv(url)
        for r in rows:
            r["_season"] = yr
        all_rows.extend(r for r in rows if r.get("game_type") == "R")

    # Current season — piggyback on the standard cache to avoid double-fetching
    current_rows = get_pitcher_statcast(mlbam_id)
    for r in current_rows:
        r.setdefault("_season", current)
    all_rows.extend(current_rows)

    _cache_set(key, all_rows)
    return all_rows


def get_phillies_luck(lucky: bool) -> dict[str, list[dict]]:
    """
    Return {'hitters': [...], 'pitchers': [...]} with the top-3 luckiest or
    unluckiest Phillies players based on a combined net score.

    Hitter score  = net hits added   (lucky hits − unlucky outs)
    Pitcher score = net hits saved   (lucky outs − unlucky hits allowed)

    lucky=True  → top 3 by highest score (most positive)
    lucky=False → top 3 by lowest score  (most negative)

    Each entry: {'name': str, 'score': float, 'player_id': int}.
    """
    roster = get_phillies_roster()
    player_info = {
        p["id"]: {
            "name": p["fullName"],
            "is_pitcher": p.get("primaryPosition", {}).get("abbreviation", "") == "P",
        }
        for p in roster
    }

    # --- Hitters ---
    batter_rows = _get_phillies_batter_statcast()
    batter_groups: dict[str, list[dict]] = defaultdict(list)
    for row in batter_rows:
        b = row.get("batter", "")
        if b:
            batter_groups[b].append(row)

    hitter_scores: list[dict] = []
    for pid_str, grp in batter_groups.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        info = player_info.get(pid)
        if info is None or info["is_pitcher"]:
            continue
        score = _hitter_luck_score(grp)
        hitter_scores.append({"name": info["name"], "score": round(score, 2), "player_id": pid})

    # --- Pitchers ---
    pitcher_rows = _get_phillies_pitcher_statcast()
    pitcher_groups: dict[str, list[dict]] = defaultdict(list)
    for row in pitcher_rows:
        p = row.get("pitcher", "")
        if p:
            pitcher_groups[p].append(row)

    pitcher_scores: list[dict] = []
    for pid_str, grp in pitcher_groups.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        info = player_info.get(pid)
        if info is None or not info["is_pitcher"]:
            continue
        score = _pitcher_luck_score(grp)
        pitcher_scores.append({"name": info["name"], "score": round(score, 2), "player_id": pid})

    # Luckiest: highest scores; Unluckiest: lowest scores
    hitter_scores.sort(key=lambda x: x["score"], reverse=lucky)
    pitcher_scores.sort(key=lambda x: x["score"], reverse=lucky)
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


def get_phillies_roster_full() -> list[dict]:
    """
    Return the full Phillies 40-man roster including IL players (1-hour cache).

    Each entry: {id, fullName, position, status_code, on_il, is_pitcher}
    status_code examples: "A" = Active, "IL10", "IL15", "IL60" = injured list.
    """
    key = f"roster_full_{CURRENT_SEASON}"
    cached = _cache_get(key, 3600)
    if cached is not None:
        return cached

    try:
        data = statsapi.get(
            "team_roster",
            {
                "teamId": PHILLIES_TEAM_ID,
                "rosterType": "40Man",
                "season": CURRENT_SEASON,
            },
        )
        players = []
        for entry in data.get("roster", []):
            status_code = entry.get("status", {}).get("code", "A")
            position = entry.get("position", {}).get("abbreviation", "")
            players.append({
                "id": entry["person"]["id"],
                "fullName": entry["person"]["fullName"],
                "position": position,
                "status_code": status_code,
                "on_il": status_code not in ("A", ""),
                "is_pitcher": position == "P",
            })
        _cache_set(key, players)
        return players
    except Exception:
        return []


def fetch_statcast_for_range(
    mlbam_id: int,
    player_type: str,
    start: str,
    end: str,
) -> list[dict]:
    """
    Fetch Statcast rows for a player over a specific date range (no cache).

    player_type: "batter" or "pitcher"
    start / end:  YYYY-MM-DD strings (both inclusive)
    """
    game_type = get_game_type()
    if player_type == "batter":
        url = _statcast_batter_url(mlbam_id, start, end, game_type)
    else:
        url = _statcast_pitcher_url(mlbam_id, start, end, game_type)
    rows = _fetch_statcast_csv(url)
    return [r for r in rows if r.get("game_type") == game_type]


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
            group_name = group.get("group", "").lower()
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
            group_name = group.get("group", "").lower()
            for season_entry in group.get("splits", []):
                entry = dict(season_entry.get("stat", {}))
                entry["season"] = season_entry.get("season", "")
                entry["group"] = group_name
                seasons.append(entry)
        return seasons
    except Exception:
        return []


def get_live_game_data(game_pk: int) -> Optional[dict]:
    """Return live game data dict from statsapi, cached for 25 seconds."""
    cache_key = f"live_feed_{game_pk}"
    cached = _cache_get(cache_key, 25)
    if cached is not None:
        return cached
    try:
        result = statsapi.get("game", {"gamePk": game_pk})
        if result:
            _cache_set(cache_key, result)
        return result
    except Exception:
        return None


def get_todays_phillies_games() -> list[dict]:
    """Return today's Phillies games from the schedule, cached for 2 minutes."""
    cache_key = f"phillies_schedule_{date.today().isoformat()}"
    cached = _cache_get(cache_key, 120)
    if cached is not None:
        return cached
    try:
        today = date.today().strftime("%Y-%m-%d")
        result = statsapi.schedule(date=today, team=PHILLIES_TEAM_ID)
        _cache_set(cache_key, result)
        return result
    except Exception:
        return []


def get_todays_non_phillies_games() -> list[dict]:
    """
    Return today's MLB games that do NOT involve the Phillies (team 143).
    Fetches the full schedule and filters out any game where either team is PHI.
    Cached for 90 seconds to avoid hammering the API on every 30-second monitor tick.
    """
    cache_key = f"non_phillies_schedule_{date.today().isoformat()}"
    cached = _cache_get(cache_key, 90)
    if cached is not None:
        return cached
    try:
        today = date.today().strftime("%Y-%m-%d")
        all_games = statsapi.schedule(date=today, sportId=1)
        result = [
            g for g in all_games
            if g.get("away_id") != PHILLIES_TEAM_ID
            and g.get("home_id") != PHILLIES_TEAM_ID
        ]
        _cache_set(cache_key, result)
        return result
    except Exception:
        return []


def get_next_game_with_probables(days_ahead: int = 10) -> Optional[dict]:
    """
    Find the next upcoming Phillies game (within days_ahead days) that has at
    least one probable pitcher announced.

    Returns a dict with:
      game_date, game_pk, status,
      home_team / away_team: {id, name, abbreviation},
      phi_is_home: bool,
      phi_probable: {id, fullName} or None,
      opp_probable: {id, fullName} or None,
      opponent: {id, name, abbreviation}

    Returns None if no game is found in the window.
    """
    today = date.today()
    end = today + __import__("datetime").timedelta(days=days_ahead)
    try:
        data = statsapi.get(
            "schedule",
            {
                "sportId": 1,
                "teamId": PHILLIES_TEAM_ID,
                "startDate": today.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
                "gameType": "S,R",
                "hydrate": "probablePitcher,team",
            },
        )
    except Exception:
        return None

    terminal = {"Final", "Game Over", "Completed Early"}
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {}).get("detailedState", "")
            if status in terminal:
                continue

            home = game.get("teams", {}).get("home", {})
            away = game.get("teams", {}).get("away", {})

            home_id = home.get("team", {}).get("id")
            phi_is_home = home_id == PHILLIES_TEAM_ID

            phi_side = home if phi_is_home else away
            opp_side = away if phi_is_home else home

            phi_prob = phi_side.get("probablePitcher")
            opp_prob = opp_side.get("probablePitcher")

            opp_team = opp_side.get("team", {})

            return {
                "game_date": date_entry.get("date", ""),
                "game_pk": game.get("gamePk"),
                "status": status,
                "phi_is_home": phi_is_home,
                "phi_probable": (
                    {"id": phi_prob["id"], "fullName": phi_prob["fullName"]}
                    if phi_prob else None
                ),
                "opp_probable": (
                    {"id": opp_prob["id"], "fullName": opp_prob["fullName"]}
                    if opp_prob else None
                ),
                "opponent": {
                    "id": opp_team.get("id"),
                    "name": opp_team.get("name", "Opponent"),
                    "abbreviation": opp_team.get("abbreviation", "OPP"),
                },
                "home_team": {
                    "id": home.get("team", {}).get("id"),
                    "name": home.get("team", {}).get("name", ""),
                    "abbreviation": home.get("team", {}).get("abbreviation", ""),
                },
                "away_team": {
                    "id": away.get("team", {}).get("id"),
                    "name": away.get("team", {}).get("name", ""),
                    "abbreviation": away.get("team", {}).get("abbreviation", ""),
                },
            }
    return None


def get_opponent_roster_batters(team_id: int) -> list[dict]:
    """
    Return the active roster non-pitchers (hitters) for any team (1-hour cache).

    Each entry: {id, fullName, position}
    """
    key = f"opp_roster_batters_{team_id}_{CURRENT_SEASON}"
    cached = _cache_get(key, 3600)
    if cached is not None:
        return cached

    try:
        data = statsapi.get(
            "team_roster",
            {"teamId": team_id, "rosterType": "active", "season": CURRENT_SEASON},
        )
        players = []
        for entry in data.get("roster", []):
            pos = entry.get("position", {}).get("abbreviation", "")
            if pos == "P":
                continue
            players.append({
                "id": entry["person"]["id"],
                "fullName": entry["person"]["fullName"],
                "position": pos,
            })
        _cache_set(key, players)
        return players
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Stolen base Statcast leaderboards
# ---------------------------------------------------------------------------

_SAVANT_SPRINT_SPEED_URL = (
    "https://baseballsavant.mlb.com/sprint_speed_leaderboard"
    "?year={year}&type=runner&min=0&csv=true"
)

_SAVANT_POP_TIME_URL = (
    "https://baseballsavant.mlb.com/leaderboard/pop-time"
    "?min_season={year}&max_season={year}&team=&player_id=&min=1&csv=true"
)


def get_sprint_speed_leaderboard() -> dict[int, dict]:
    """
    Return a mapping of player_id → {sprint_speed, lead_distance, name}
    for all MLB runners this season (12-hour cache).

    sprint_speed is in ft/s. lead_distance is ft (None if not in CSV).
    """
    key = f"sprint_speed_{CURRENT_SEASON}"
    cached = _cache_get(key, 12 * 3600)
    if cached is not None:
        return cached

    url = _SAVANT_SPRINT_SPEED_URL.format(year=CURRENT_SEASON)
    rows = _fetch_statcast_csv(url)
    result: dict[int, dict] = {}
    for row in rows:
        pid = _to_int(row.get("player_id") or row.get("mlbam_id", 0))
        if not pid:
            continue
        speed = _to_float(row.get("sprint_speed"))
        if speed is None:
            continue
        first = str(row.get("first_name", "")).strip()
        last = str(row.get("last_name", "")).strip()
        name = f"{first} {last}".strip() if (first or last) else str(row.get("player_name", ""))
        lead = _to_float(row.get("lead_distance"))  # present in some exports, None if absent
        result[pid] = {"sprint_speed": speed, "lead_distance": lead, "name": name}

    _cache_set(key, result)
    return result


def get_pop_time_leaderboard() -> dict[int, dict]:
    """
    Return a mapping of catcher player_id → {pop_time, name} for all MLB
    catchers this season (12-hour cache).

    pop_time is in seconds (average pop time to 2B on steal attempts).
    """
    key = f"pop_time_{CURRENT_SEASON}"
    cached = _cache_get(key, 12 * 3600)
    if cached is not None:
        return cached

    url = _SAVANT_POP_TIME_URL.format(year=CURRENT_SEASON)
    rows = _fetch_statcast_csv(url)
    result: dict[int, dict] = {}
    for row in rows:
        pid = _to_int(row.get("player_id") or row.get("catcher_id", 0))
        if not pid:
            continue
        # Try multiple possible column names
        pop = (
            _to_float(row.get("pop_2b_sba"))
            or _to_float(row.get("pop_2b_cs"))
            or _to_float(row.get("pop_time"))
        )
        if pop is None:
            continue
        name = (
            str(row.get("player_name", "")).strip()
            or (str(row.get("first_name", "")).strip() + " " + str(row.get("last_name", "")).strip()).strip()
        )
        result[pid] = {"pop_time": pop, "name": name}

    _cache_set(key, result)
    return result


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


# ---------------------------------------------------------------------------
# Historical roster / stats helpers (for /remember)
# ---------------------------------------------------------------------------

_STATSAPI_BASE = "https://statsapi.mlb.com/api/v1"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _fetch_json(url: str) -> dict:
    """
    Fetch a JSON URL, trying curl_cffi (Chrome impersonation) first to bypass
    Akamai JA3 fingerprint blocks that cause 406 errors with plain
    requests/statsapi, then urllib with browser headers.

    Raises RuntimeError naming every attempt's failure if none succeed.
    """
    import json as _json
    import urllib.request as _ur

    errors: list[str] = []
    try:
        from curl_cffi import requests as _cffi
    except ImportError:
        _cffi = None
        errors.append("curl_cffi not installed")

    if _cffi is not None:
        try:
            resp = _cffi.get(url, impersonate="chrome124", timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            errors.append(f"curl_cffi: {exc}")

    try:
        req = _ur.Request(url, headers=_BROWSER_HEADERS)
        with _ur.urlopen(req, timeout=30) as r:
            return _json.loads(r.read())
    except Exception as exc:
        errors.append(f"urllib: {exc}")

    # statsapi itself is built on requests, so try it too in case it's the one
    # route the host allows.
    try:
        import requests as _requests
        resp = _requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        errors.append(f"requests: {exc}")

    raise RuntimeError("; ".join(errors))


# The bot host's IP is blocked by statsapi.mlb.com's Akamai edge (406 on every
# client), so /remember reads seasons from a bundled snapshot built off-host by
# scripts/build_remember_data.py. If the deployed copy is missing, it's pulled
# from the public GitHub repo (not behind MLB's edge) and saved locally. Live
# MLB fetches are only a last resort for seasons the snapshot lacks.
REMEMBER_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "remember_seasons.json"
REMEMBER_DATA_URL = (
    "https://raw.githubusercontent.com/thatsmyboye/philliestherapy/main/"
    "projects/phillies-bot/data/remember_seasons.json"
)
REMEMBER_HITTING_FIELDS = ("plateAppearances", "avg", "obp", "slg", "homeRuns", "rbi")
REMEMBER_PITCHING_FIELDS = ("inningsPitched", "era", "strikeOuts", "baseOnBalls")
# After a failed load, wait this long before trying the file/download again.
_REMEMBER_RETRY_SECONDS = 600

_bundled_seasons: Optional[dict[str, list]] = None
_bundle_error: Optional[str] = None
_bundle_failed_at = 0.0


def compact_remember_player(player: dict) -> list:
    """Pack a player entry into a [id, name, position, hitting, pitching] row."""
    def _pack(stats: dict, fields: tuple[str, ...]) -> Optional[list]:
        return [stats.get(f) for f in fields] if stats else None

    return [
        player["id"],
        player["fullName"],
        player["position"],
        _pack(player.get("hitting", {}), REMEMBER_HITTING_FIELDS),
        _pack(player.get("pitching", {}), REMEMBER_PITCHING_FIELDS),
    ]


def _expand_remember_row(row: list) -> dict:
    pid, name, position, hitting, pitching = row
    return {
        "id": pid,
        "fullName": name,
        "position": position,
        "hitting": dict(zip(REMEMBER_HITTING_FIELDS, hitting)) if hitting else {},
        "pitching": dict(zip(REMEMBER_PITCHING_FIELDS, pitching)) if pitching else {},
    }


def _read_remember_file() -> dict[str, list]:
    with open(REMEMBER_DATA_FILE, encoding="utf-8") as f:
        seasons = json.load(f).get("seasons") or {}
    if not seasons:
        raise ValueError("file has no seasons")
    return seasons


def _download_remember_file() -> dict[str, list]:
    """Fetch the snapshot from GitHub and save it locally for later restarts."""
    data = _fetch_json(REMEMBER_DATA_URL)
    seasons = data.get("seasons") or {}
    if not seasons:
        raise ValueError("downloaded file has no seasons")
    try:
        REMEMBER_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = REMEMBER_DATA_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(REMEMBER_DATA_FILE)
    except Exception as exc:
        print(f"[remember] downloaded season data but couldn't save it: {exc}")
    return seasons


def load_bundled_remember_seasons() -> dict[str, list]:
    """
    Return the bundled {season: [rows]} snapshot: the local file, else a copy
    downloaded from GitHub. Returns {} (and retries after a cool-down) if both
    fail; the reason is kept in _bundle_error.
    """
    global _bundled_seasons, _bundle_error, _bundle_failed_at
    if _bundled_seasons is not None:
        return _bundled_seasons
    if _bundle_failed_at and time.time() - _bundle_failed_at < _REMEMBER_RETRY_SECONDS:
        return {}

    try:
        _bundled_seasons = _read_remember_file()
        return _bundled_seasons
    except Exception as exc:
        local_error = f"{REMEMBER_DATA_FILE} unreadable ({exc})"
        print(f"[remember] {local_error}; downloading from GitHub")

    try:
        _bundled_seasons = _download_remember_file()
        print(f"[remember] downloaded {len(_bundled_seasons)} seasons from GitHub")
        return _bundled_seasons
    except Exception as exc:
        _bundle_error = f"{local_error}; GitHub download failed ({exc})"
        _bundle_failed_at = time.time()
        print(f"[remember] {_bundle_error}")
        return {}


def get_phillies_season_player_stats(year: int) -> list[dict]:
    """
    Return every player who appeared for the Phillies in the given season, with
    their Phillies-only hitting and pitching lines.

    Reads the bundled snapshot first; falls back to a live fetch for seasons it
    lacks. Raises RuntimeError if neither source has the season.
    """
    seasons = load_bundled_remember_seasons()
    rows = seasons.get(str(year))
    if rows is not None:
        return [_expand_remember_row(r) for r in rows]
    try:
        return fetch_phillies_season_player_stats(year)
    except RuntimeError as exc:
        if not seasons:
            raise RuntimeError(
                f"season data unavailable: {_bundle_error}; live MLB fetch failed too ({exc})"
            ) from exc
        raise


def fetch_phillies_season_player_stats(year: int) -> list[dict]:
    """
    Fetch every player who appeared for the Phillies in the given season from
    the MLB Stats API, with their Phillies-only hitting and pitching lines
    (24-hour cache).

    Uses two team-filtered /stats queries (hitting + pitching) plus the season
    roster (for positions) instead of one request per player, so /remember stays
    fast and isn't throttled.

    Each entry: {id, fullName, position, hitting: {...}, pitching: {...}}
    Stat dicts are empty if the player had no appearances in that role.
    Returns [] for a season with no games; raises RuntimeError if the stats
    requests themselves fail, so callers can tell the two apart.
    """
    key = f"phillies_season_player_stats_{year}"
    cached = _cache_get(key, 24 * 3600)
    if cached is not None:
        return cached

    # The stats splits sometimes label position "X" (unknown); the season roster
    # carries the real position, so prefer it when available.
    roster_positions: dict[int, str] = {}
    try:
        roster = _fetch_json(
            f"{_STATSAPI_BASE}/teams/{PHILLIES_TEAM_ID}/roster"
            f"?rosterType=fullSeason&season={year}"
        )
        for entry in roster.get("roster", []):
            pos = entry.get("position", {}).get("abbreviation")
            if pos:
                roster_positions[entry["person"]["id"]] = pos
    except Exception as exc:
        print(f"[remember] {year} roster fetch failed (positions only): {exc}")

    players: dict[int, dict] = {}
    for group in ("hitting", "pitching"):
        url = (
            f"{_STATSAPI_BASE}/stats?stats=season&group={group}"
            f"&teamId={PHILLIES_TEAM_ID}&season={year}&sportId=1"
            f"&playerPool=ALL&limit=500"
        )
        try:
            data = _fetch_json(url)
        except Exception as exc:
            print(f"[remember] {year} {group} stats fetch failed: {exc}")
            raise RuntimeError(f"{group} stats request failed ({exc})") from exc

        for stat_group in data.get("stats", []):
            for split in stat_group.get("splits", []):
                if split.get("team", {}).get("id") != PHILLIES_TEAM_ID:
                    continue
                person = split.get("player", {})
                pid = person.get("id")
                if pid is None:
                    continue
                entry = players.setdefault(pid, {
                    "id": pid,
                    "fullName": person.get("fullName", "Unknown"),
                    "position": roster_positions.get(pid)
                    or split.get("position", {}).get("abbreviation", "?"),
                    "hitting": {},
                    "pitching": {},
                })
                entry[group] = split.get("stat", {})

    result = list(players.values())
    if result:
        _cache_set(key, result)
    return result


# ---------------------------------------------------------------------------
# Generic team helpers (used by the web app; bot uses the Phillies-specific versions above)
# ---------------------------------------------------------------------------

def get_all_mlb_teams() -> list[dict]:
    """Return all MLB teams sorted by name (24-hour cache). Each entry: {id, name, abbreviation, league, division}."""
    key = "all_mlb_teams"
    cached = _cache_get(key, 24 * 3600)
    if cached is not None:
        return cached
    try:
        data = statsapi.get("teams", {"sportId": 1, "hydrate": "division,league"})
        teams = []
        for t in data.get("teams", []):
            if not t.get("active", True):
                continue
            teams.append({
                "id": t["id"],
                "name": t.get("name", ""),
                "abbreviation": t.get("abbreviation", ""),
                "league": t.get("league", {}).get("name", ""),
                "league_id": t.get("league", {}).get("id"),
                "division": t.get("division", {}).get("name", ""),
            })
        teams.sort(key=lambda x: x["name"])
        _cache_set(key, teams)
        return teams
    except Exception:
        return []


def get_team_roster(team_id: int) -> list[dict]:
    """Return the 40-man roster for any team (1-hour cache). Each entry: {id, fullName, position, status_code, on_il, is_pitcher}."""
    key = f"team_roster_{team_id}_{CURRENT_SEASON}"
    cached = _cache_get(key, 3600)
    if cached is not None:
        return cached
    try:
        data = statsapi.get(
            "team_roster",
            {"teamId": team_id, "rosterType": "40Man", "season": CURRENT_SEASON},
        )
        players = []
        for entry in data.get("roster", []):
            status_code = entry.get("status", {}).get("code", "A")
            position = entry.get("position", {}).get("abbreviation", "")
            players.append({
                "id": entry["person"]["id"],
                "fullName": entry["person"]["fullName"],
                "position": position,
                "status_code": status_code,
                "on_il": status_code not in ("A", ""),
                "is_pitcher": position == "P",
            })
        _cache_set(key, players)
        return players
    except Exception:
        return []


def get_todays_games(team_id: Optional[int] = None) -> list[dict]:
    """Return today's MLB schedule, optionally filtered to a single team (2-minute cache)."""
    key = f"schedule_{date.today().isoformat()}_{team_id or 'all'}"
    cached = _cache_get(key, 120)
    if cached is not None:
        return cached
    try:
        today = date.today().strftime("%Y-%m-%d")
        kwargs: dict = {"date": today, "sportId": 1}
        if team_id:
            kwargs["team"] = team_id
        result = statsapi.schedule(**kwargs)
        _cache_set(key, result)
        return result
    except Exception:
        return []


def get_next_game_with_probables_for_team(team_id: int, days_ahead: int = 10) -> Optional[dict]:
    """
    Generic version of get_next_game_with_probables() for any team.

    Returns the same shape dict as get_next_game_with_probables() but with
    'team_is_home' (bool) and 'team_probable' / 'opp_probable' instead of phi_*.
    """
    today = date.today()
    end = today + __import__("datetime").timedelta(days=days_ahead)
    try:
        data = statsapi.get(
            "schedule",
            {
                "sportId": 1,
                "teamId": team_id,
                "startDate": today.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
                "gameType": "S,R",
                "hydrate": "probablePitcher,team",
            },
        )
    except Exception:
        return None

    terminal = {"Final", "Game Over", "Completed Early"}
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {}).get("detailedState", "")
            if status in terminal:
                continue

            home = game.get("teams", {}).get("home", {})
            away = game.get("teams", {}).get("away", {})
            home_id = home.get("team", {}).get("id")
            team_is_home = home_id == team_id

            team_side = home if team_is_home else away
            opp_side = away if team_is_home else home

            team_prob = team_side.get("probablePitcher")
            opp_prob = opp_side.get("probablePitcher")
            opp_team = opp_side.get("team", {})

            return {
                "game_date": date_entry.get("date", ""),
                "game_pk": game.get("gamePk"),
                "status": status,
                "team_is_home": team_is_home,
                "team_probable": (
                    {"id": team_prob["id"], "fullName": team_prob["fullName"]}
                    if team_prob else None
                ),
                "opp_probable": (
                    {"id": opp_prob["id"], "fullName": opp_prob["fullName"]}
                    if opp_prob else None
                ),
                "opponent": {
                    "id": opp_team.get("id"),
                    "name": opp_team.get("name", "Opponent"),
                    "abbreviation": opp_team.get("abbreviation", "OPP"),
                },
                "home_team": {
                    "id": home.get("team", {}).get("id"),
                    "name": home.get("team", {}).get("name", ""),
                    "abbreviation": home.get("team", {}).get("abbreviation", ""),
                },
                "away_team": {
                    "id": away.get("team", {}).get("id"),
                    "name": away.get("team", {}).get("name", ""),
                    "abbreviation": away.get("team", {}).get("abbreviation", ""),
                },
            }
    return None


def get_team_batter_statcast(team_abbr: str) -> list[dict]:
    """Fetch all batter Statcast events for any team this season (4-hour cache)."""
    year = _current_year()
    key = f"team_batter_statcast_{team_abbr}_{year}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    url = _statcast_team_url(team_abbr, "batter", get_season_start(), today, get_game_type())
    rows = _fetch_statcast_csv(url)
    result = [r for r in rows if r.get("game_type") == get_game_type()]
    _cache_set(key, result)
    return result


def get_team_luck(team_abbr: str, team_id: int, lucky: bool) -> dict[str, list[dict]]:
    """
    Generic version of get_phillies_luck() for any team.

    team_abbr: Baseball Savant abbreviation (e.g. "PHI", "NYY")
    team_id:   MLBAM team ID (for roster lookup)
    lucky:     True → top 3 luckiest; False → top 3 unluckiest
    """
    from collections import defaultdict as _defaultdict

    roster = get_team_roster(team_id)
    player_info = {
        p["id"]: {"name": p["fullName"], "is_pitcher": p["is_pitcher"]}
        for p in roster
    }

    batter_rows = get_team_batter_statcast(team_abbr)
    batter_groups: dict[str, list[dict]] = _defaultdict(list)
    for row in batter_rows:
        b = row.get("batter", "")
        if b:
            batter_groups[b].append(row)

    hitter_scores: list[dict] = []
    for pid_str, grp in batter_groups.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        info = player_info.get(pid)
        if info is None or info["is_pitcher"]:
            continue
        score = _hitter_luck_score(grp)
        hitter_scores.append({"name": info["name"], "score": round(score, 2), "player_id": pid})

    pitcher_rows = get_team_pitcher_statcast(team_abbr)
    pitcher_groups: dict[str, list[dict]] = _defaultdict(list)
    for row in pitcher_rows:
        p = row.get("pitcher", "")
        if p:
            pitcher_groups[p].append(row)

    pitcher_scores: list[dict] = []
    for pid_str, grp in pitcher_groups.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        info = player_info.get(pid)
        if info is None or not info["is_pitcher"]:
            continue
        score = _pitcher_luck_score(grp)
        pitcher_scores.append({"name": info["name"], "score": round(score, 2), "player_id": pid})

    hitter_scores.sort(key=lambda x: x["score"], reverse=lucky)
    pitcher_scores.sort(key=lambda x: x["score"], reverse=lucky)
    return {"hitters": hitter_scores[:3], "pitchers": pitcher_scores[:3]}
