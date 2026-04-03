"""
Stat definitions and fetching utilities for the live props system.

Supports both per-game (live boxscore) and season (statsapi) stat retrieval.
"""
from __future__ import annotations

from typing import Optional

import statsapi

from utils.mlb_data import _cache_get, _cache_set, CURRENT_SEASON

# ── Stat definitions ─────────────────────────────────────────────────────────
# Keys:
#   display             — human-readable label used in embeds
#   game_batting_key    — key in live boxscore batting stats dict (None = N/A)
#   season_batting_key  — key in statsapi season hitting stats (None = N/A)
#   game_pitching_key   — key in live boxscore pitching stats dict (None = N/A)
#   season_pitching_key — key in statsapi season pitching stats (None = N/A)
#
# Special "__COMPUTED_*__" values trigger manual computation in get_game_stats
# since those stats aren't directly present in the per-game boxscore.

STAT_DEFINITIONS: dict[str, dict] = {
    "hits": {
        "display": "Hits",
        "game_batting_key": "hits",
        "season_batting_key": "hits",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "home_runs": {
        "display": "Home Runs",
        "game_batting_key": "homeRuns",
        "season_batting_key": "homeRuns",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "rbi": {
        "display": "RBI",
        "game_batting_key": "rbi",
        "season_batting_key": "rbi",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "stolen_bases": {
        "display": "Stolen Bases",
        "game_batting_key": "stolenBases",
        "season_batting_key": "stolenBases",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "total_bases": {
        "display": "Total Bases",
        "game_batting_key": "__COMPUTED_TB__",
        "season_batting_key": "totalBases",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "walks": {
        "display": "Walks",
        "game_batting_key": "baseOnBalls",
        "season_batting_key": "baseOnBalls",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "strikeouts_batter": {
        "display": "Strikeouts (Batter)",
        "game_batting_key": "strikeOuts",
        "season_batting_key": "strikeOuts",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "doubles": {
        "display": "Doubles",
        "game_batting_key": "doubles",
        "season_batting_key": "doubles",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "strikeouts_pitcher": {
        "display": "Strikeouts (Pitcher)",
        "game_batting_key": None,
        "season_batting_key": None,
        "game_pitching_key": "strikeOuts",
        "season_pitching_key": "strikeOuts",
    },
    "wins": {
        "display": "Wins",
        "game_batting_key": None,
        "season_batting_key": None,
        "game_pitching_key": None,
        "season_pitching_key": "wins",
    },
    "saves": {
        "display": "Saves",
        "game_batting_key": None,
        "season_batting_key": None,
        "game_pitching_key": "saves",
        "season_pitching_key": "saves",
    },
    "innings_pitched": {
        "display": "Innings Pitched",
        "game_batting_key": None,
        "season_batting_key": None,
        "game_pitching_key": "inningsPitched",
        "season_pitching_key": "inningsPitched",
    },
    # ── Rate stats ────────────────────────────────────────────────────────────
    # Season values come directly from statsapi as strings like ".325".
    # Game values are computed from the live boxscore.
    "avg": {
        "display": "AVG",
        "game_batting_key": "__COMPUTED_AVG__",
        "season_batting_key": "avg",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "obp": {
        "display": "OBP",
        "game_batting_key": "__COMPUTED_OBP__",
        "season_batting_key": "obp",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "slg": {
        "display": "SLG",
        "game_batting_key": "__COMPUTED_SLG__",
        "season_batting_key": "slg",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    "ops": {
        "display": "OPS",
        "game_batting_key": "__COMPUTED_OPS__",
        "season_batting_key": "ops",
        "game_pitching_key": None,
        "season_pitching_key": None,
    },
    # ── Pitcher counting stats ────────────────────────────────────────────────
    "games_started": {
        "display": "Games Started",
        "game_batting_key": None,
        "season_batting_key": None,
        "game_pitching_key": None,
        "season_pitching_key": "gamesStarted",
    },
    # ── Pitcher rate stats ────────────────────────────────────────────────────
    # Season value comes from statsapi as a string like "3.45".
    # Game value is computed from the live boxscore earned runs and innings pitched.
    "era": {
        "display": "ERA",
        "game_batting_key": None,
        "season_batting_key": None,
        "game_pitching_key": "__COMPUTED_ERA__",
        "season_pitching_key": "era",
    },
}

# Stats that are only meaningful as season props (no per-game tracking).
SEASON_ONLY_STATS = {"wins", "games_started"}

# Stats whose values are rates (displayed as .300 rather than whole numbers).
RATE_STATS = {"avg", "obp", "slg", "ops"}


def get_game_stats(feed: dict, player_id: int, stat: str) -> Optional[float]:
    """
    Extract a player's current game stat from a live-feed boxscore.

    Returns None if the player isn't in the game or the stat doesn't apply.
    """
    defn = STAT_DEFINITIONS.get(stat)
    if not defn:
        return None

    boxscore = feed.get("liveData", {}).get("boxscore", {})
    pid_key = f"ID{player_id}"

    for side in ("home", "away"):
        players = boxscore.get("teams", {}).get(side, {}).get("players", {})
        if pid_key not in players:
            continue

        player_stats = players[pid_key].get("stats", {})

        # Try batting
        game_bkey = defn.get("game_batting_key")
        if game_bkey:
            batting = player_stats.get("batting", {})
            if batting:
                computed = _compute_game_batting(batting, game_bkey)
                if computed is not None:
                    return computed
                val = batting.get(game_bkey)
                if val is not None:
                    return _coerce(val, stat)

        # Try pitching
        game_pkey = defn.get("game_pitching_key")
        if game_pkey:
            pitching = player_stats.get("pitching", {})
            if pitching:
                computed = _compute_game_pitching(pitching, game_pkey)
                if computed is not None:
                    return computed
                val = pitching.get(game_pkey)
                if val is not None:
                    return _coerce(val, stat)

        # Player is in game but stat not applicable
        return None

    return None  # Player not in this game's boxscore


def get_season_stats(player_id: int, stat: str) -> Optional[float]:
    """
    Fetch a player's current season stat total via statsapi.

    Results are cached for 5 minutes to avoid API spam on the 30-second loop.
    """
    defn = STAT_DEFINITIONS.get(stat)
    if not defn:
        return None

    cache_key = f"props_season_{player_id}_{CURRENT_SEASON}"
    cached = _cache_get(cache_key, 300)
    if cached is not None:
        all_stats: dict = cached
    else:
        try:
            data = statsapi.player_stat_data(
                player_id,
                group="[hitting,pitching]",
                type="season",
            )
        except Exception:
            return None
        all_stats = {"hitting": {}, "pitching": {}}
        for group in data.get("stats", []):
            group_name = group.get("group", "").lower()
            if group_name in all_stats:
                all_stats[group_name] = group.get("stats", {})
        _cache_set(cache_key, all_stats)

    # Try hitting
    s_bkey = defn.get("season_batting_key")
    if s_bkey:
        val = all_stats.get("hitting", {}).get(s_bkey)
        if val is not None:
            return _coerce(val, stat)

    # Try pitching
    s_pkey = defn.get("season_pitching_key")
    if s_pkey:
        val = all_stats.get("pitching", {}).get(s_pkey)
        if val is not None:
            return _coerce(val, stat)

    return None


def _compute_game_batting(batting: dict, key: str) -> Optional[float]:
    """
    Handle __COMPUTED_*__ keys that require arithmetic over multiple boxscore fields.
    Returns None if the key is not a computed sentinel (caller falls through to direct lookup).
    """
    if key == "__COMPUTED_TB__":
        h  = int(batting.get("hits", 0) or 0)
        d  = int(batting.get("doubles", 0) or 0)
        t  = int(batting.get("triples", 0) or 0)
        hr = int(batting.get("homeRuns", 0) or 0)
        return float(h + d + 2 * t + 3 * hr)

    if key == "__COMPUTED_AVG__":
        ab = int(batting.get("atBats", 0) or 0)
        h  = int(batting.get("hits", 0) or 0)
        return round(h / ab, 3) if ab else 0.0

    if key == "__COMPUTED_OBP__":
        ab  = int(batting.get("atBats", 0) or 0)
        h   = int(batting.get("hits", 0) or 0)
        bb  = int(batting.get("baseOnBalls", 0) or 0)
        hbp = int(batting.get("hitByPitch", 0) or 0)
        sf  = int(batting.get("sacFlies", 0) or 0)
        denom = ab + bb + hbp + sf
        return round((h + bb + hbp) / denom, 3) if denom else 0.0

    if key == "__COMPUTED_SLG__":
        ab = int(batting.get("atBats", 0) or 0)
        h  = int(batting.get("hits", 0) or 0)
        d  = int(batting.get("doubles", 0) or 0)
        t  = int(batting.get("triples", 0) or 0)
        hr = int(batting.get("homeRuns", 0) or 0)
        tb = h + d + 2 * t + 3 * hr
        return round(tb / ab, 3) if ab else 0.0

    if key == "__COMPUTED_OPS__":
        ab  = int(batting.get("atBats", 0) or 0)
        h   = int(batting.get("hits", 0) or 0)
        d   = int(batting.get("doubles", 0) or 0)
        t   = int(batting.get("triples", 0) or 0)
        hr  = int(batting.get("homeRuns", 0) or 0)
        bb  = int(batting.get("baseOnBalls", 0) or 0)
        hbp = int(batting.get("hitByPitch", 0) or 0)
        sf  = int(batting.get("sacFlies", 0) or 0)
        obp_denom = ab + bb + hbp + sf
        obp = (h + bb + hbp) / obp_denom if obp_denom else 0.0
        tb  = h + d + 2 * t + 3 * hr
        slg = tb / ab if ab else 0.0
        return round(obp + slg, 3)

    return None  # Not a computed key


def _compute_game_pitching(pitching: dict, key: str) -> Optional[float]:
    """
    Handle __COMPUTED_*__ keys for pitching stats that require arithmetic.
    Returns None if the key is not a computed sentinel (caller falls through to direct lookup).
    """
    if key == "__COMPUTED_ERA__":
        er = int(pitching.get("earnedRuns", 0) or 0)
        ip = parse_ip(str(pitching.get("inningsPitched", "0") or "0"))
        return round((er / ip) * 9, 2) if ip else 0.0

    return None  # Not a computed key


def parse_ip(ip_str: str) -> float:
    """Convert '5.2' innings-pitched string to a decimal float (5.667)."""
    try:
        parts = str(ip_str).split(".")
        full = int(parts[0])
        outs = int(parts[1]) if len(parts) > 1 else 0
        return round(full + outs / 3, 2)
    except (ValueError, IndexError):
        return 0.0


def _coerce(val: object, stat: str) -> float:
    if stat == "innings_pitched":
        return parse_ip(str(val))
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
