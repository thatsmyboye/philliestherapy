"""
MLB data helpers: Baseball Savant Statcast queries (direct CSV) and statsapi
wrappers, with simple in-memory TTL caching to avoid hammering the data sources.
"""
from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
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

# Season configuration
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
    return (
        f"{_SAVANT_BASE}?player_type=pitcher"
        f"&pitchers_lookup%5B%5D={mlbam_id}"
        f"&game_date_gt={start}&game_date_lt={end}"
        f"&hfGT={game_type}%7C&hfSea={CURRENT_SEASON}%7C"
        f"&type=details&all=true"
    )


def _statcast_batter_url(mlbam_id: int, start: str, end: str, game_type: str) -> str:
    return (
        f"{_SAVANT_BASE}?player_type=batter"
        f"&batters_lookup%5B%5D={mlbam_id}"
        f"&game_date_gt={start}&game_date_lt={end}"
        f"&hfGT={game_type}%7C&hfSea={CURRENT_SEASON}%7C"
        f"&type=details&all=true"
    )


def _statcast_team_url(
    team: str, player_type: str, start: str, end: str, game_type: str
) -> str:
    return (
        f"{_SAVANT_BASE}?player_type={player_type}"
        f"&team={team}"
        f"&game_date_gt={start}&game_date_lt={end}"
        f"&hfGT={game_type}%7C&hfSea={CURRENT_SEASON}%7C"
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
    key = f"team_batter_statcast_PHI_{CURRENT_SEASON}"
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
    key = f"team_pitcher_statcast_PHI_{CURRENT_SEASON}"
    cached = _cache_get(key, 4 * 3600)
    if cached is not None:
        return cached
    today = date.today().strftime("%Y-%m-%d")
    url = _statcast_team_url("PHI", "pitcher", get_season_start(), today, get_game_type())
    rows = _fetch_statcast_csv(url)
    result = [r for r in rows if r.get("game_type") == get_game_type()]
    _cache_set(key, result)
    return result


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
            "roster",
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
