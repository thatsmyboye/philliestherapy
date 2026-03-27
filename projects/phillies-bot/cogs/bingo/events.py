"""
Event pool definitions, player assignment, and play-by-play detection
for the Phillies Bingo game.

All events are Phillies-centric:
  - BATTER events fire when a Phillies batter is involved
  - PITCHER events fire when a Phillies pitcher is involved
  - GAME events fire for team/game-level occurrences (always "Any")
"""
from __future__ import annotations

import random
from typing import Optional

PHILLIES_TEAM_ID = 143

# ---------------------------------------------------------------------------
# Event definitions
# ---------------------------------------------------------------------------

# Category constants
BATTER = "BATTER"
PITCHER = "PITCHER"
GAME = "GAME"

# Full pool of event IDs — 26 total; draw 24 per game day
EVENT_POOL_IDS: list[str] = [
    # BATTER events (14)
    "HR", "DOUBLE", "TRIPLE",
    "STOLEN_BASE", "CAUGHT_STEAL",
    "HBP", "WALK", "INTENT_WALK",
    "K_SWING", "K_LOOK",
    "SAC_BUNT", "SAC_FLY", "FIELDERS_CH", "GRAND_SLAM",
    # PITCHER events (4)
    "PITCHER_K", "BALK", "WILD_PITCH", "PICKOFF",
    # GAME events (8) — always "Any", no specific player
    "PASSED_BALL", "ERROR", "DOUBLE_PLAY", "TRIPLE_PLAY",
    "CATCHER_INT", "LEAD_CHANGE", "EXTRA_INN", "PHI_COMEBACK",
]

# League pool — identical to EVENT_POOL_IDS but COMEBACK replaces PHI_COMEBACK
LEAGUE_EVENT_POOL_IDS: list[str] = [
    # BATTER events (14)
    "HR", "DOUBLE", "TRIPLE",
    "STOLEN_BASE", "CAUGHT_STEAL",
    "HBP", "WALK", "INTENT_WALK",
    "K_SWING", "K_LOOK",
    "SAC_BUNT", "SAC_FLY", "FIELDERS_CH", "GRAND_SLAM",
    # PITCHER events (4)
    "PITCHER_K", "BALK", "WILD_PITCH", "PICKOFF",
    # GAME events (8) — always "Any", no specific player
    "PASSED_BALL", "ERROR", "DOUBLE_PLAY", "TRIPLE_PLAY",
    "CATCHER_INT", "LEAD_CHANGE", "EXTRA_INN", "COMEBACK",
]

# Event category map
EVENT_CATEGORY: dict[str, str] = {
    "HR": BATTER, "DOUBLE": BATTER, "TRIPLE": BATTER,
    "STOLEN_BASE": BATTER, "CAUGHT_STEAL": BATTER,
    "HBP": BATTER, "WALK": BATTER, "INTENT_WALK": BATTER,
    "K_SWING": BATTER, "K_LOOK": BATTER,
    "SAC_BUNT": BATTER, "SAC_FLY": BATTER,
    "FIELDERS_CH": BATTER, "GRAND_SLAM": BATTER,
    "PITCHER_K": PITCHER, "BALK": PITCHER,
    "WILD_PITCH": PITCHER, "PICKOFF": PITCHER,
    "PASSED_BALL": GAME, "ERROR": GAME, "DOUBLE_PLAY": GAME,
    "TRIPLE_PLAY": GAME, "CATCHER_INT": GAME,
    "LEAD_CHANGE": GAME, "EXTRA_INN": GAME, "PHI_COMEBACK": GAME,
    "COMEBACK": GAME,
}

# Base short labels (appended after player name abbreviation)
EVENT_BASE_LABEL: dict[str, str] = {
    "HR": "HR", "DOUBLE": "2B", "TRIPLE": "3B",
    "STOLEN_BASE": "SB", "CAUGHT_STEAL": "CS",
    "HBP": "HBP", "WALK": "BB", "INTENT_WALK": "IBB",
    "K_SWING": "K-Sw", "K_LOOK": "K-Lo",
    "SAC_BUNT": "SacBnt", "SAC_FLY": "SacFly",
    "FIELDERS_CH": "FC", "GRAND_SLAM": "GrSlam",
    "PITCHER_K": "K", "BALK": "Balk",
    "WILD_PITCH": "WP", "PICKOFF": "Pkoff",
    "PASSED_BALL": "PB", "ERROR": "Error",
    "DOUBLE_PLAY": "DP", "TRIPLE_PLAY": "3Play",
    "CATCHER_INT": "CI", "LEAD_CHANGE": "LdChng",
    "EXTRA_INN": "Extras", "PHI_COMEBACK": "ComeBk",
    "COMEBACK": "ComeBk",
}

WIN_TYPES: list[str] = [
    "standard",
    "four_corners",
    "postage_stamp",
    "blackout",
    "x_pattern",
    "outside_edges",
]

WIN_TYPE_LABELS: dict[str, str] = {
    "standard": "Standard (any row, column, or diagonal)",
    "four_corners": "Four Corners",
    "postage_stamp": "Postage Stamp (any 2×2 block)",
    "blackout": "Blackout (all 25 squares)",
    "x_pattern": "X Pattern (both diagonals)",
    "outside_edges": "Outside Edges (all 16 perimeter squares)",
}


# ---------------------------------------------------------------------------
# Player name abbreviation
# ---------------------------------------------------------------------------

def abbrev_name(last_name: str) -> str:
    """Return up to 4 chars of a last name for board display."""
    return last_name[:4] if len(last_name) > 4 else last_name


def make_label(event_id: str, player_name: str) -> str:
    """Build the board cell label, e.g. 'Schw HR' or 'Any BB'."""
    base = EVENT_BASE_LABEL[event_id]
    prefix = abbrev_name(player_name) if player_name != "Any" else "Any"
    label = f"{prefix} {base}"
    # Hard-cap at 9 chars to preserve column alignment
    return label[:9]


# ---------------------------------------------------------------------------
# Daily pool drawing and player assignment
# ---------------------------------------------------------------------------

def draw_daily_pool(game_date: str) -> list[str]:
    """
    Randomly draw 24 event IDs from EVENT_POOL_IDS for the given game date.
    Deterministic: same date always yields the same draw.
    """
    rng = random.Random(game_date)
    return rng.sample(EVENT_POOL_IDS, 24)


def draw_daily_pool_league(game_date: str) -> list[str]:
    """
    Randomly draw 24 event IDs from LEAGUE_EVENT_POOL_IDS for the given game date.
    Deterministic: same date always yields the same draw.
    Uses a different seed suffix to ensure independence from the Phillies pool draw.
    """
    rng = random.Random(game_date + ":league")
    return rng.sample(LEAGUE_EVENT_POOL_IDS, 24)


def pick_win_type(game_date: str) -> str:
    """Pick today's win type deterministically from game_date."""
    rng = random.Random(game_date + ":win")
    return rng.choice(WIN_TYPES)


def assign_players_to_pool(
    event_ids: list[str],
    game_date: str,
    roster: list[dict],
) -> list[dict]:
    """
    Build the full list of 24 square dicts, each with player assignment.

    Each square is:
      {event_id, player_id, player_name, label, category}

    GAME events always get player_id=None ("Any").
    BATTER/PITCHER events get a 50/50 random flip: specific Phillies player
    or "Any".  If no compatible roster player is available, falls back to Any.

    roster entries: {id, fullName, is_pitcher, ...}
    """
    position_players = [p for p in roster if not p.get("is_pitcher")]
    pitchers = [p for p in roster if p.get("is_pitcher")]

    squares: list[dict] = []
    for idx, event_id in enumerate(event_ids):
        category = EVENT_CATEGORY[event_id]
        rng = random.Random(f"{game_date}:{event_id}:{idx}")

        if category == GAME:
            player_id = None
            player_name = "Any"
        else:
            pool = position_players if category == BATTER else pitchers
            if pool and rng.random() >= 0.5:
                player = rng.choice(pool)
                # Use last name for display
                full = player["fullName"]
                last = full.split()[-1]
                player_id = player["id"]
                player_name = last
            else:
                player_id = None
                player_name = "Any"

        squares.append({
            "event_id": event_id,
            "player_id": player_id,
            "player_name": player_name,
            "label": make_label(event_id, player_name),
            "category": category,
        })

    return squares


def assign_any_pool(event_ids: list[str]) -> list[dict]:
    """
    Build a list of 24 square dicts where every square uses player_id=None ("Any").
    Used for the league bingo variant where no specific team's roster is tracked.
    """
    return [
        {
            "event_id": event_id,
            "player_id": None,
            "player_name": "Any",
            "label": make_label(event_id, "Any"),
            "category": EVENT_CATEGORY[event_id],
        }
        for event_id in event_ids
    ]


def make_fingerprint(square: dict) -> str:
    """Return a unique key for a square, e.g. 'HR:656775' or 'WALK:any'."""
    pid = square.get("player_id")
    return f"{square['event_id']}:{pid if pid is not None else 'any'}"


# ---------------------------------------------------------------------------
# Live-feed helper utilities
# ---------------------------------------------------------------------------

def _get_batting_team_id(play: dict, feed: dict) -> Optional[int]:
    """Return the batting team's MLB team ID for this play."""
    half = play.get("about", {}).get("halfInning", "")
    teams = feed.get("gameData", {}).get("teams", {})
    if half == "top":
        return teams.get("away", {}).get("id")
    elif half == "bottom":
        return teams.get("home", {}).get("id")
    return None


def _get_pitching_team_id(play: dict, feed: dict) -> Optional[int]:
    """Return the pitching/fielding team's MLB team ID for this play."""
    half = play.get("about", {}).get("halfInning", "")
    teams = feed.get("gameData", {}).get("teams", {})
    if half == "top":
        return teams.get("home", {}).get("id")
    elif half == "bottom":
        return teams.get("away", {}).get("id")
    return None


# ---------------------------------------------------------------------------
# Per-play event matching
# ---------------------------------------------------------------------------

_STOLEN_BASE_TYPES = {"stolen_base_2b", "stolen_base_3b", "stolen_base_home"}
_CAUGHT_STEAL_TYPES = {"caught_stealing_2b", "caught_stealing_3b", "caught_stealing_home"}
_PICKOFF_TYPES = {"pickoff", "pickoff_1b", "pickoff_2b", "pickoff_3b"}
_DP_TYPES = {"double_play", "grounded_into_double_play"}
_FC_TYPES = {"fielders_choice", "fielders_choice_out"}


def _matches_batter_event(event_id: str, event_type: str, desc: str, rbi: int) -> bool:
    if event_id == "HR":
        return event_type == "home_run"
    if event_id == "DOUBLE":
        return event_type == "double"
    if event_id == "TRIPLE":
        return event_type == "triple"
    if event_id == "STOLEN_BASE":
        return event_type in _STOLEN_BASE_TYPES
    if event_id == "CAUGHT_STEAL":
        return event_type in _CAUGHT_STEAL_TYPES
    if event_id == "HBP":
        return event_type == "hit_by_pitch"
    if event_id == "WALK":
        return event_type == "walk"
    if event_id == "INTENT_WALK":
        return event_type == "intent_walk"
    if event_id == "K_SWING":
        return event_type == "strikeout" and "swinging" in desc
    if event_id == "K_LOOK":
        return event_type == "strikeout" and "called" in desc
    if event_id == "SAC_BUNT":
        return event_type == "sac_bunt"
    if event_id == "SAC_FLY":
        return event_type == "sac_fly"
    if event_id == "FIELDERS_CH":
        return event_type in _FC_TYPES
    if event_id == "GRAND_SLAM":
        return event_type == "home_run" and rbi >= 4
    return False


def _matches_pitcher_event(event_id: str, event_type: str, desc: str) -> bool:
    if event_id == "PITCHER_K":
        return event_type == "strikeout"
    if event_id == "BALK":
        return event_type == "balk"
    if event_id == "WILD_PITCH":
        return event_type == "wild_pitch"
    if event_id == "PICKOFF":
        return event_type in _PICKOFF_TYPES
    return False


def _matches_game_event(event_id: str, event_type: str, pitching_team: Optional[int]) -> bool:
    """
    For GAME events, check only the eventType (with team filter where applicable).
    LEAD_CHANGE, EXTRA_INN, PHI_COMEBACK are checked separately from the linescore.
    """
    if event_id == "PASSED_BALL":
        return event_type == "passed_ball" and pitching_team == PHILLIES_TEAM_ID
    if event_id == "ERROR":
        return event_type == "field_error" and pitching_team == PHILLIES_TEAM_ID
    if event_id == "DOUBLE_PLAY":
        return event_type in _DP_TYPES and pitching_team == PHILLIES_TEAM_ID
    if event_id == "TRIPLE_PLAY":
        return event_type == "triple_play" and pitching_team == PHILLIES_TEAM_ID
    if event_id == "CATCHER_INT":
        return event_type == "catcher_interf" and pitching_team == PHILLIES_TEAM_ID
    # LEAD_CHANGE, EXTRA_INN, PHI_COMEBACK handled via linescore; never match here
    return False


def _matches_game_event_any(event_id: str, event_type: str) -> bool:
    """
    Like _matches_game_event but without any team-ID filter.
    Used for the league bingo variant.
    LEAD_CHANGE, EXTRA_INN, COMEBACK are still handled via linescore.
    """
    if event_id == "PASSED_BALL":
        return event_type == "passed_ball"
    if event_id == "ERROR":
        return event_type == "field_error"
    if event_id == "DOUBLE_PLAY":
        return event_type in _DP_TYPES
    if event_id == "TRIPLE_PLAY":
        return event_type == "triple_play"
    if event_id == "CATCHER_INT":
        return event_type == "catcher_interf"
    return False


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def detect_events(
    play: dict,
    feed: dict,
    pool_squares: list[dict],
    already_marked: set[str],
) -> list[str]:
    """
    Inspect a single completed play and return a list of square fingerprints
    that are newly triggered by this play.

    Does NOT handle linescore-level events (LEAD_CHANGE, EXTRA_INN,
    PHI_COMEBACK) — those are checked separately in the monitor loop.
    """
    if not play.get("about", {}).get("isComplete", False):
        return []

    result = play.get("result", {})
    matchup = play.get("matchup", {})

    event_type: str = result.get("eventType", "")
    desc: str = result.get("description", "").lower()
    rbi: int = result.get("rbi", 0)
    batter_id: Optional[int] = matchup.get("batter", {}).get("id")
    pitcher_id: Optional[int] = matchup.get("pitcher", {}).get("id")

    batting_team = _get_batting_team_id(play, feed)
    pitching_team = _get_pitching_team_id(play, feed)

    triggered: list[str] = []

    for square in pool_squares:
        fingerprint = make_fingerprint(square)
        if fingerprint in already_marked:
            continue

        cat = square["category"]
        pid = square["player_id"]  # None == "Any Phillies player"
        eid = square["event_id"]

        matched = False

        if cat == BATTER and batting_team == PHILLIES_TEAM_ID:
            if pid is None or batter_id == pid:
                matched = _matches_batter_event(eid, event_type, desc, rbi)

        elif cat == PITCHER and pitching_team == PHILLIES_TEAM_ID:
            if pid is None or pitcher_id == pid:
                matched = _matches_pitcher_event(eid, event_type, desc)

        elif cat == GAME:
            matched = _matches_game_event(eid, event_type, pitching_team)

        if matched:
            triggered.append(fingerprint)

    return triggered


def detect_events_league(
    play: dict,
    pool_squares: list[dict],
    already_marked: set[str],
) -> list[str]:
    """
    Like detect_events() but fires for any team in any game (no Phillies filter).
    Used by the league bingo monitor.

    Does NOT handle linescore-level events (LEAD_CHANGE, EXTRA_INN, COMEBACK).
    """
    if not play.get("about", {}).get("isComplete", False):
        return []

    result = play.get("result", {})
    matchup = play.get("matchup", {})

    event_type: str = result.get("eventType", "")
    desc: str = result.get("description", "").lower()
    rbi: int = result.get("rbi", 0)
    batter_id: Optional[int] = matchup.get("batter", {}).get("id")
    pitcher_id: Optional[int] = matchup.get("pitcher", {}).get("id")

    triggered: list[str] = []

    for square in pool_squares:
        fingerprint = make_fingerprint(square)
        if fingerprint in already_marked:
            continue

        cat = square["category"]
        pid = square["player_id"]  # always None for league (all "Any")
        eid = square["event_id"]

        matched = False

        if cat == BATTER:
            if pid is None or batter_id == pid:
                matched = _matches_batter_event(eid, event_type, desc, rbi)

        elif cat == PITCHER:
            if pid is None or pitcher_id == pid:
                matched = _matches_pitcher_event(eid, event_type, desc)

        elif cat == GAME:
            matched = _matches_game_event_any(eid, event_type)

        if matched:
            triggered.append(fingerprint)

    return triggered


# ---------------------------------------------------------------------------
# Linescore-level event detection (called from monitor loop)
# ---------------------------------------------------------------------------

def detect_linescore_events(
    feed: dict,
    prev_snapshot: Optional[dict],
    already_marked: set[str],
    pool_squares: list[dict],
) -> tuple[list[str], dict]:
    """
    Check feed's linescore for LEAD_CHANGE, EXTRA_INN, and PHI_COMEBACK.
    Returns (fingerprints, new_snapshot).

    prev_snapshot: {"phi_score": int, "opp_score": int, "inning": int} or None
    """
    linescore = feed.get("liveData", {}).get("linescore", {})
    game_data = feed.get("gameData", {})
    home_id = game_data.get("teams", {}).get("home", {}).get("id")

    runs = linescore.get("teams", {})
    home_runs = runs.get("home", {}).get("runs", 0) or 0
    away_runs = runs.get("away", {}).get("runs", 0) or 0
    current_inning = linescore.get("currentInning", 0) or 0

    phi_is_home = (home_id == PHILLIES_TEAM_ID)
    phi_score = home_runs if phi_is_home else away_runs
    opp_score = away_runs if phi_is_home else home_runs

    triggered: list[str] = []
    square_map = {s["event_id"]: make_fingerprint(s) for s in pool_squares if s["event_id"] in ("LEAD_CHANGE", "EXTRA_INN", "PHI_COMEBACK")}

    # EXTRA_INN: game enters 10th or beyond
    fp_extra = square_map.get("EXTRA_INN")
    if fp_extra and fp_extra not in already_marked and current_inning > 9:
        triggered.append(fp_extra)

    if prev_snapshot is not None:
        prev_phi = prev_snapshot.get("phi_score", 0)
        prev_opp = prev_snapshot.get("opp_score", 0)

        def _leader(phi: int, opp: int) -> Optional[str]:
            if phi > opp:
                return "phi"
            if opp > phi:
                return "opp"
            return None  # tie

        prev_leader = _leader(prev_phi, prev_opp)
        curr_leader = _leader(phi_score, opp_score)

        if prev_leader != curr_leader and curr_leader is not None:
            # LEAD_CHANGE
            fp_lc = square_map.get("LEAD_CHANGE")
            if fp_lc and fp_lc not in already_marked:
                triggered.append(fp_lc)

            # PHI_COMEBACK: Phillies specifically just took the lead
            if curr_leader == "phi":
                fp_cb = square_map.get("PHI_COMEBACK")
                if fp_cb and fp_cb not in already_marked:
                    triggered.append(fp_cb)

    return triggered, {"phi_score": phi_score, "opp_score": opp_score, "inning": current_inning}


def detect_linescore_events_league(
    feed: dict,
    prev_snapshot: Optional[dict],
    already_marked: set[str],
    pool_squares: list[dict],
) -> tuple[list[str], dict]:
    """
    Like detect_linescore_events() but for any game (no Phillies perspective).
    Checks for LEAD_CHANGE, EXTRA_INN, and COMEBACK (generic comeback).

    prev_snapshot: {"home_score": int, "away_score": int, "inning": int} or None
    Returns (fingerprints, new_snapshot).
    """
    linescore = feed.get("liveData", {}).get("linescore", {})

    runs = linescore.get("teams", {})
    home_score = runs.get("home", {}).get("runs", 0) or 0
    away_score = runs.get("away", {}).get("runs", 0) or 0
    current_inning = linescore.get("currentInning", 0) or 0

    triggered: list[str] = []
    square_map = {
        s["event_id"]: make_fingerprint(s)
        for s in pool_squares
        if s["event_id"] in ("LEAD_CHANGE", "EXTRA_INN", "COMEBACK")
    }

    # EXTRA_INN: game enters 10th or beyond
    fp_extra = square_map.get("EXTRA_INN")
    if fp_extra and fp_extra not in already_marked and current_inning > 9:
        triggered.append(fp_extra)

    if prev_snapshot is not None:
        prev_home = prev_snapshot.get("home_score", 0)
        prev_away = prev_snapshot.get("away_score", 0)

        def _leader(home: int, away: int) -> Optional[str]:
            if home > away:
                return "home"
            if away > home:
                return "away"
            return None  # tie

        prev_leader = _leader(prev_home, prev_away)
        curr_leader = _leader(home_score, away_score)

        if prev_leader != curr_leader and curr_leader is not None:
            # LEAD_CHANGE: any team takes or retakes the lead
            fp_lc = square_map.get("LEAD_CHANGE")
            if fp_lc and fp_lc not in already_marked:
                triggered.append(fp_lc)

            # COMEBACK: a team that was trailing (prev_leader not None) takes the lead
            if prev_leader is not None:
                fp_cb = square_map.get("COMEBACK")
                if fp_cb and fp_cb not in already_marked:
                    triggered.append(fp_cb)

    return triggered, {"home_score": home_score, "away_score": away_score, "inning": current_inning}


# ---------------------------------------------------------------------------
# Lineup re-roll
# ---------------------------------------------------------------------------

def reroll_scratched_players(
    pool_squares: list[dict],
    lineup_player_ids: set[int],
    game_date: str,
) -> list[dict]:
    """
    For any square with a specific player not in lineup_player_ids,
    replace that square's player assignment with "Any".

    Returns the updated pool_squares list (mutated in place, also returned).
    """
    for square in pool_squares:
        pid = square.get("player_id")
        if pid is not None and pid not in lineup_player_ids:
            square["player_id"] = None
            square["player_name"] = "Any"
            square["label"] = make_label(square["event_id"], "Any")
    return pool_squares


def get_phillies_lineup_ids(feed: dict) -> set[int]:
    """
    Extract all Phillies player IDs present in the game's lineup
    (both batting order and pitchers list) from a live feed.
    """
    game_data = feed.get("gameData", {})
    home_id = game_data.get("teams", {}).get("home", {}).get("id")
    phi_side = "home" if home_id == PHILLIES_TEAM_ID else "away"

    boxscore_teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    phi_team = boxscore_teams.get(phi_side, {})

    ids: set[int] = set()
    for pid in phi_team.get("battingOrder", []):
        ids.add(int(pid))
    for pid in phi_team.get("pitchers", []):
        ids.add(int(pid))
    # Also include bullpen (pitchers who may enter but aren't yet active)
    for pid in phi_team.get("bullpen", []):
        ids.add(int(pid))
    return ids
