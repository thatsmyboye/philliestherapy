"""
Tests for the Bingo game engine.
Run from the project root: python -m pytest cogs/bingo/tests.py -v
"""

import pytest

from cogs.bingo.events import (
    WIN_TYPES, EVENT_POOL_IDS, LEAGUE_EVENT_POOL_IDS,
    draw_daily_pool, draw_daily_pool_league, pick_win_type,
    assign_players_to_pool, assign_any_pool,
    make_fingerprint, make_label,
    detect_events, detect_events_league,
    detect_linescore_events, detect_linescore_events_league,
    PHILLIES_TEAM_ID,
)
from cogs.bingo.board import generate_layout
from cogs.bingo.win_checker import check_win, build_marked_grid


# ── Helpers ───────────────────────────────────────────────────────────────────

def _full(n: int) -> list[list[bool]]:
    """n×n grid with all True."""
    return [[True] * n for _ in range(n)]


def _empty(n: int) -> list[list[bool]]:
    """n×n grid with all False."""
    return [[False] * n for _ in range(n)]


def _set(n: int, cells: list[tuple[int, int]]) -> list[list[bool]]:
    """n×n grid with only the given (row, col) cells set True."""
    g = _empty(n)
    for r, c in cells:
        g[r][c] = True
    return g


def _pool(event_ids: list[str]) -> list[dict]:
    """Build a minimal pool_squares list from event IDs (all Any)."""
    return assign_any_pool(event_ids)


def _play(event_type: str, desc: str = "", rbi: int = 0,
          batter_id: int = 1, pitcher_id: int = 2,
          half: str = "top") -> dict:
    """Build a minimal completed play dict."""
    return {
        "about": {"isComplete": True, "halfInning": half},
        "result": {"eventType": event_type, "description": desc, "rbi": rbi},
        "matchup": {
            "batter": {"id": batter_id},
            "pitcher": {"id": pitcher_id},
        },
    }


def _feed(home_id: int = PHILLIES_TEAM_ID, away_id: int = 999) -> dict:
    """Build a minimal game feed with home/away team IDs."""
    return {
        "gameData": {
            "teams": {
                "home": {"id": home_id},
                "away": {"id": away_id},
            }
        }
    }


def _phi_pool() -> list[dict]:
    """Draw today's Phillies pool as dicts with all-Any players."""
    ids = draw_daily_pool("2025-06-01")
    return assign_players_to_pool(ids, "2025-06-01", [])


# ── draw_daily_pool ───────────────────────────────────────────────────────────

def test_phillies_pool_size():
    pool = draw_daily_pool("2025-06-01")
    assert len(pool) == 16


def test_phillies_pool_is_subset():
    pool = draw_daily_pool("2025-06-01")
    assert all(e in EVENT_POOL_IDS for e in pool)


def test_phillies_pool_no_duplicates():
    pool = draw_daily_pool("2025-06-01")
    assert len(set(pool)) == len(pool)


def test_phillies_pool_deterministic():
    assert draw_daily_pool("2025-06-01") == draw_daily_pool("2025-06-01")


def test_phillies_pool_varies_by_date():
    assert draw_daily_pool("2025-06-01") != draw_daily_pool("2025-06-02")


def test_league_pool_size():
    pool = draw_daily_pool_league("2025-06-01")
    assert len(pool) == 24


def test_league_pool_is_subset():
    pool = draw_daily_pool_league("2025-06-01")
    assert all(e in LEAGUE_EVENT_POOL_IDS for e in pool)


def test_league_pool_no_duplicates():
    pool = draw_daily_pool_league("2025-06-01")
    assert len(set(pool)) == len(pool)


def test_league_pool_deterministic():
    assert draw_daily_pool_league("2025-06-01") == draw_daily_pool_league("2025-06-01")


def test_phillies_and_league_pools_independent():
    p = draw_daily_pool("2025-06-01")
    l = draw_daily_pool_league("2025-06-01")
    assert p != l[:16], "Phillies and league draws should differ (different seeds)"


# ── pick_win_type ─────────────────────────────────────────────────────────────

def test_pick_win_type_valid():
    wt = pick_win_type("2025-06-01")
    assert wt in WIN_TYPES


def test_pick_win_type_deterministic():
    assert pick_win_type("2025-06-01") == pick_win_type("2025-06-01")


def test_pick_win_type_varies_by_date():
    types = {pick_win_type(f"2025-06-{d:02d}") for d in range(1, 10)}
    assert len(types) > 1, "Win types should vary across different dates"


# ── make_fingerprint ──────────────────────────────────────────────────────────

def test_fingerprint_any_player():
    sq = {"event_id": "HR", "player_id": None}
    assert make_fingerprint(sq) == "HR:any"


def test_fingerprint_specific_player():
    sq = {"event_id": "WALK", "player_id": 656775}
    assert make_fingerprint(sq) == "WALK:656775"


def test_fingerprint_team_id():
    sq = {"event_id": "DOUBLE", "player_id": 143}
    assert make_fingerprint(sq) == "DOUBLE:143"


# ── make_label ────────────────────────────────────────────────────────────────

def test_make_label_any():
    assert make_label("HR", "Any") == "~HR"


def test_make_label_any_two_char_code():
    assert make_label("STOLEN_BASE", "Any") == "~SB"


def test_make_label_player():
    assert make_label("HR", "Wheeler") == "WhHR"


def test_make_label_short_name():
    assert make_label("HR", "Li") == "LiHR"


def test_make_label_max_length():
    lbl = make_label("WALK", "Longname")
    assert len(lbl) <= 4


# ── generate_layout ───────────────────────────────────────────────────────────

def test_phillies_layout_shape():
    layout = generate_layout(16, "123:2025-06-01", grid_size=4, free_center=False)
    assert len(layout) == 4
    assert all(len(row) == 4 for row in layout)


def test_phillies_layout_indices():
    layout = generate_layout(16, "123:2025-06-01", grid_size=4, free_center=False)
    flat = [cell for row in layout for cell in row]
    assert sorted(flat) == list(range(16))


def test_phillies_layout_no_free_center():
    layout = generate_layout(16, "123:2025-06-01", grid_size=4, free_center=False)
    flat = [cell for row in layout for cell in row]
    assert -1 not in flat


def test_league_layout_shape():
    layout = generate_layout(24, "123:2025-06-01", grid_size=5, free_center=True)
    assert len(layout) == 5
    assert all(len(row) == 5 for row in layout)


def test_league_layout_free_center():
    layout = generate_layout(24, "123:2025-06-01", grid_size=5, free_center=True)
    assert layout[2][2] == -1


def test_league_layout_indices():
    layout = generate_layout(24, "123:2025-06-01", grid_size=5, free_center=True)
    flat = [cell for row in layout for cell in row]
    non_free = [c for c in flat if c != -1]
    assert sorted(non_free) == list(range(24))
    assert flat.count(-1) == 1


def test_layout_deterministic():
    l1 = generate_layout(16, "123:2025-06-01", grid_size=4, free_center=False)
    l2 = generate_layout(16, "123:2025-06-01", grid_size=4, free_center=False)
    assert l1 == l2


def test_layout_varies_by_seed():
    l1 = generate_layout(16, "111:2025-06-01", grid_size=4, free_center=False)
    l2 = generate_layout(16, "222:2025-06-01", grid_size=4, free_center=False)
    assert l1 != l2


def test_layout_wrong_pool_size_raises():
    with pytest.raises(ValueError):
        generate_layout(15, "123:2025-06-01", grid_size=4, free_center=False)


def test_layout_wrong_pool_size_free_center_raises():
    with pytest.raises(ValueError):
        generate_layout(25, "123:2025-06-01", grid_size=5, free_center=True)


# ── build_marked_grid ─────────────────────────────────────────────────────────

def _make_layout_and_pool():
    """Build a minimal 5×5 layout + pool for marking tests."""
    pool = assign_any_pool(draw_daily_pool_league("2025-06-01"))
    layout = generate_layout(24, "123:2025-06-01", grid_size=5, free_center=True)
    return layout, pool


def test_build_marked_grid_free_center_always_true():
    layout, pool = _make_layout_and_pool()
    grid = build_marked_grid(layout, pool, set(), free_center=True)
    assert grid[2][2] is True


def test_build_marked_grid_empty_marks():
    layout, pool = _make_layout_and_pool()
    grid = build_marked_grid(layout, pool, set(), free_center=True)
    non_center = [grid[r][c] for r in range(5) for c in range(5) if (r, c) != (2, 2)]
    assert not any(non_center)


def test_build_marked_grid_specific_mark():
    layout, pool = _make_layout_and_pool()
    # Find which square is at position (0, 0)
    idx = layout[0][0]
    sq = pool[idx]
    fp = make_fingerprint(sq)
    grid = build_marked_grid(layout, pool, {fp}, free_center=True)
    assert grid[0][0] is True


def test_build_marked_grid_no_free_center():
    pool = assign_any_pool(draw_daily_pool("2025-06-01"))
    layout = generate_layout(16, "123:2025-06-01", grid_size=4, free_center=False)
    grid = build_marked_grid(layout, pool, set(), free_center=False)
    assert all(not grid[r][c] for r in range(4) for c in range(4))


# ── check_win: standard ───────────────────────────────────────────────────────

def test_standard_row_win_4x4():
    g = _set(4, [(1, 0), (1, 1), (1, 2), (1, 3)])
    assert check_win(g, "standard") is True


def test_standard_col_win_4x4():
    g = _set(4, [(0, 2), (1, 2), (2, 2), (3, 2)])
    assert check_win(g, "standard") is True


def test_standard_diag_win_4x4():
    g = _set(4, [(0, 0), (1, 1), (2, 2), (3, 3)])
    assert check_win(g, "standard") is True


def test_standard_anti_diag_win_4x4():
    g = _set(4, [(0, 3), (1, 2), (2, 1), (3, 0)])
    assert check_win(g, "standard") is True


def test_standard_no_win_4x4():
    g = _set(4, [(0, 0), (1, 1), (2, 2)])
    assert check_win(g, "standard") is False


def test_standard_row_win_5x5():
    g = _set(5, [(2, 0), (2, 1), (2, 2), (2, 3), (2, 4)])
    assert check_win(g, "standard") is True


def test_standard_no_win_partial_row():
    g = _set(5, [(2, 0), (2, 1), (2, 2), (2, 3)])
    assert check_win(g, "standard") is False


# ── check_win: four_corners ───────────────────────────────────────────────────

def test_four_corners_win():
    for n in (4, 5):
        last = n - 1
        g = _set(n, [(0, 0), (0, last), (last, 0), (last, last)])
        assert check_win(g, "four_corners") is True


def test_four_corners_missing_one():
    g = _set(4, [(0, 0), (0, 3), (3, 0)])
    assert check_win(g, "four_corners") is False


# ── check_win: postage_stamp ──────────────────────────────────────────────────

def test_postage_stamp_top_left():
    g = _set(4, [(0, 0), (0, 1), (1, 0), (1, 1)])
    assert check_win(g, "postage_stamp") is True


def test_postage_stamp_bottom_right():
    g = _set(5, [(3, 3), (3, 4), (4, 3), (4, 4)])
    assert check_win(g, "postage_stamp") is True


def test_postage_stamp_not_contiguous():
    g = _set(4, [(0, 0), (0, 2), (2, 0), (2, 2)])
    assert check_win(g, "postage_stamp") is False


def test_postage_stamp_missing_one():
    g = _set(4, [(0, 0), (0, 1), (1, 0)])
    assert check_win(g, "postage_stamp") is False


# ── check_win: blackout ───────────────────────────────────────────────────────

def test_blackout_full():
    for n in (4, 5):
        assert check_win(_full(n), "blackout") is True


def test_blackout_one_missing():
    g = _full(4)
    g[2][2] = False
    assert check_win(g, "blackout") is False


# ── check_win: x_pattern ──────────────────────────────────────────────────────

def test_x_pattern_win_5x5():
    cells = [(i, i) for i in range(5)] + [(i, 4 - i) for i in range(5)]
    g = _set(5, cells)
    assert check_win(g, "x_pattern") is True


def test_x_pattern_only_one_diag():
    g = _set(5, [(i, i) for i in range(5)])
    assert check_win(g, "x_pattern") is False


def test_x_pattern_win_4x4():
    cells = [(i, i) for i in range(4)] + [(i, 3 - i) for i in range(4)]
    g = _set(4, cells)
    assert check_win(g, "x_pattern") is True


# ── check_win: outside_edges ──────────────────────────────────────────────────

def _edges(n: int) -> list[tuple[int, int]]:
    cells = []
    for c in range(n):
        cells.append((0, c))
        cells.append((n - 1, c))
    for r in range(1, n - 1):
        cells.append((r, 0))
        cells.append((r, n - 1))
    return cells


def test_outside_edges_win_5x5():
    g = _set(5, _edges(5))
    assert check_win(g, "outside_edges") is True


def test_outside_edges_win_4x4():
    g = _set(4, _edges(4))
    assert check_win(g, "outside_edges") is True


def test_outside_edges_missing_one():
    cells = _edges(5)
    cells.remove((0, 2))
    g = _set(5, cells)
    assert check_win(g, "outside_edges") is False


def test_outside_edges_inner_not_required():
    cells = _edges(5)
    g = _set(5, cells)
    assert check_win(g, "outside_edges") is True


# ── check_win: invalid inputs ─────────────────────────────────────────────────

def test_check_win_unknown_type():
    assert check_win(_full(4), "not_a_type") is False


def test_check_win_empty_grid():
    assert check_win([], "standard") is False


def test_check_win_jagged_grid():
    g = [[True, True], [True]]
    assert check_win(g, "standard") is False


# ── detect_events (Phillies) ──────────────────────────────────────────────────

def test_detect_home_run():
    pool = _pool(["HR"])
    play = _play("home_run")
    result = detect_events(play, _feed(), pool, set())
    assert "HR:any" in result


def test_detect_grand_slam():
    pool = _pool(["GRAND_SLAM"])
    play = _play("home_run", rbi=4)
    result = detect_events(play, _feed(), pool, set())
    assert "GRAND_SLAM:any" in result


def test_grand_slam_requires_rbi_4():
    pool = _pool(["GRAND_SLAM"])
    play = _play("home_run", rbi=3)
    result = detect_events(play, _feed(), pool, set())
    assert "GRAND_SLAM:any" not in result


def test_detect_double():
    pool = _pool(["DOUBLE"])
    play = _play("double")
    result = detect_events(play, _feed(), pool, set())
    assert "DOUBLE:any" in result


def test_detect_stolen_base():
    pool = _pool(["STOLEN_BASE"])
    play = _play("stolen_base_2b")
    result = detect_events(play, _feed(), pool, set())
    assert "STOLEN_BASE:any" in result


def test_detect_k_swing():
    pool = _pool(["K_SWING"])
    play = _play("strikeout", desc="swinging strike")
    result = detect_events(play, _feed(), pool, set())
    assert "K_SWING:any" in result


def test_detect_k_look():
    pool = _pool(["K_LOOK"])
    play = _play("strikeout", desc="called strike")
    result = detect_events(play, _feed(), pool, set())
    assert "K_LOOK:any" in result


def test_detect_pitcher_k():
    pool = _pool(["PITCHER_K"])
    play = _play("strikeout")
    result = detect_events(play, _feed(), pool, set())
    assert "PITCHER_K:any" in result


def test_detect_wild_pitch():
    pool = _pool(["WILD_PITCH"])
    play = _play("wild_pitch")
    result = detect_events(play, _feed(), pool, set())
    assert "WILD_PITCH:any" in result


def test_detect_balk():
    pool = _pool(["BALK"])
    play = _play("balk")
    result = detect_events(play, _feed(), pool, set())
    assert "BALK:any" in result


def test_detect_pickoff():
    pool = _pool(["PICKOFF"])
    play = _play("pickoff_1b")
    result = detect_events(play, _feed(), pool, set())
    assert "PICKOFF:any" in result


def test_detect_error_game_event():
    pool = _pool(["ERROR"])
    play = _play("field_error")
    result = detect_events(play, _feed(), pool, set())
    assert "ERROR:any" in result


def test_detect_double_play():
    pool = _pool(["DOUBLE_PLAY"])
    play = _play("double_play")
    result = detect_events(play, _feed(), pool, set())
    assert "DOUBLE_PLAY:any" in result


def test_detect_incomplete_play_ignored():
    pool = _pool(["HR"])
    play = {
        "about": {"isComplete": False},
        "result": {"eventType": "home_run", "description": "", "rbi": 0},
        "matchup": {"batter": {"id": 1}, "pitcher": {"id": 2}},
    }
    result = detect_events(play, _feed(), pool, set())
    assert result == []


def test_detect_already_marked_skipped():
    pool = _pool(["HR"])
    play = _play("home_run")
    result = detect_events(play, _feed(), pool, {"HR:any"})
    assert "HR:any" not in result


def test_detect_no_match():
    pool = _pool(["HR"])
    play = _play("double")
    result = detect_events(play, _feed(), pool, set())
    assert result == []


# ── detect_events_league ──────────────────────────────────────────────────────

def test_league_detect_batter_any():
    pool = _pool(["HR"])
    play = _play("home_run", half="top")
    feed = _feed(home_id=111, away_id=222)
    result = detect_events_league(play, feed, pool, set())
    assert "HR:any" in result


def test_league_detect_batter_team_match():
    ids = ["HR"]
    squares = [{
        "event_id": "HR", "player_id": 222, "player_name": "NYM",
        "label": "~HR", "category": "BATTER",
    }]
    # batting team is away (222) when halfInning=top
    play = _play("home_run", half="top")
    feed = _feed(home_id=111, away_id=222)
    result = detect_events_league(play, feed, squares, set())
    assert "HR:222" in result


def test_league_detect_batter_team_mismatch():
    squares = [{
        "event_id": "HR", "player_id": 333, "player_name": "LAD",
        "label": "~HR", "category": "BATTER",
    }]
    play = _play("home_run", half="top")
    feed = _feed(home_id=111, away_id=222)
    result = detect_events_league(play, feed, squares, set())
    assert result == []


# ── detect_linescore_events ───────────────────────────────────────────────────

def _phi_linescore_pool() -> list[dict]:
    return [
        {"event_id": "LEAD_CHANGE", "player_id": None, "player_name": "Any",
         "label": "~LC", "category": "GAME"},
        {"event_id": "EXTRA_INN",   "player_id": None, "player_name": "Any",
         "label": "~XI", "category": "GAME"},
        {"event_id": "PHI_COMEBACK","player_id": None, "player_name": "Any",
         "label": "~CB", "category": "GAME"},
    ]


def _ls_feed(home_runs: int, away_runs: int, inning: int,
             home_id: int = PHILLIES_TEAM_ID) -> dict:
    return {
        "gameData": {"teams": {"home": {"id": home_id}, "away": {"id": 999}}},
        "liveData": {"linescore": {
            "teams": {
                "home": {"runs": home_runs},
                "away": {"runs": away_runs},
            },
            "currentInning": inning,
        }},
    }


def test_extra_innings_triggers():
    feed = _ls_feed(3, 3, 10)
    pool = _phi_linescore_pool()
    fps, snap = detect_linescore_events(feed, None, set(), pool)
    assert "EXTRA_INN:any" in fps


def test_extra_innings_not_in_9th():
    feed = _ls_feed(3, 3, 9)
    pool = _phi_linescore_pool()
    fps, snap = detect_linescore_events(feed, None, set(), pool)
    assert "EXTRA_INN:any" not in fps


def test_lead_change_triggers():
    feed = _ls_feed(3, 2, 5)  # PHI home, now winning
    pool = _phi_linescore_pool()
    prev = {"phi_score": 2, "opp_score": 2, "inning": 4}  # was tied
    fps, snap = detect_linescore_events(feed, prev, set(), pool)
    assert "LEAD_CHANGE:any" in fps


def test_phi_comeback_triggers():
    feed = _ls_feed(4, 3, 7)  # PHI home now leads
    pool = _phi_linescore_pool()
    prev = {"phi_score": 2, "opp_score": 3, "inning": 6}  # PHI was trailing
    fps, snap = detect_linescore_events(feed, prev, set(), pool)
    assert "PHI_COMEBACK:any" in fps
    assert "LEAD_CHANGE:any" in fps


def test_phi_comeback_not_when_opp_takes_lead():
    feed = _ls_feed(3, 4, 7)  # opp now leads (PHI is home)
    pool = _phi_linescore_pool()
    prev = {"phi_score": 3, "opp_score": 3, "inning": 6}
    fps, snap = detect_linescore_events(feed, prev, set(), pool)
    assert "PHI_COMEBACK:any" not in fps


def test_linescore_snapshot_returned():
    feed = _ls_feed(2, 1, 5)
    pool = _phi_linescore_pool()
    _, snap = detect_linescore_events(feed, None, set(), pool)
    assert snap["phi_score"] == 2
    assert snap["opp_score"] == 1
    assert snap["inning"] == 5


def test_linescore_already_marked_skipped():
    feed = _ls_feed(3, 3, 10)
    pool = _phi_linescore_pool()
    fps, _ = detect_linescore_events(feed, None, {"EXTRA_INN:any"}, pool)
    assert "EXTRA_INN:any" not in fps


# ── detect_linescore_events_league ────────────────────────────────────────────

def _league_linescore_pool() -> list[dict]:
    return [
        {"event_id": "LEAD_CHANGE", "player_id": None, "player_name": "Any",
         "label": "~LC", "category": "GAME"},
        {"event_id": "EXTRA_INN",   "player_id": None, "player_name": "Any",
         "label": "~XI", "category": "GAME"},
        {"event_id": "COMEBACK",    "player_id": None, "player_name": "Any",
         "label": "~CB", "category": "GAME"},
    ]


def _league_ls_feed(home_runs: int, away_runs: int, inning: int) -> dict:
    return {
        "liveData": {"linescore": {
            "teams": {
                "home": {"runs": home_runs},
                "away": {"runs": away_runs},
            },
            "currentInning": inning,
        }},
    }


def test_league_extra_innings():
    feed = _league_ls_feed(2, 2, 10)
    pool = _league_linescore_pool()
    fps, _ = detect_linescore_events_league(feed, None, set(), pool)
    assert "EXTRA_INN:any" in fps


def test_league_lead_change():
    feed = _league_ls_feed(3, 2, 5)
    pool = _league_linescore_pool()
    prev = {"home_score": 2, "away_score": 2, "inning": 4}
    fps, _ = detect_linescore_events_league(feed, prev, set(), pool)
    assert "LEAD_CHANGE:any" in fps


def test_league_comeback():
    feed = _league_ls_feed(3, 4, 8)  # away team (was trailing) now leads
    pool = _league_linescore_pool()
    prev = {"home_score": 3, "away_score": 2, "inning": 7}  # home was leading
    fps, _ = detect_linescore_events_league(feed, prev, set(), pool)
    assert "COMEBACK:any" in fps
    assert "LEAD_CHANGE:any" in fps


def test_league_no_comeback_from_tie():
    feed = _league_ls_feed(3, 4, 8)  # away takes lead from tied
    pool = _league_linescore_pool()
    prev = {"home_score": 3, "away_score": 3, "inning": 7}  # was tied
    fps, _ = detect_linescore_events_league(feed, prev, set(), pool)
    assert "LEAD_CHANGE:any" in fps
    assert "COMEBACK:any" not in fps  # not a comeback — was tied before


def test_league_snapshot_returned():
    feed = _league_ls_feed(1, 2, 3)
    pool = _league_linescore_pool()
    _, snap = detect_linescore_events_league(feed, None, set(), pool)
    assert snap["home_score"] == 1
    assert snap["away_score"] == 2
    assert snap["inning"] == 3


# ── assign_players_to_pool ────────────────────────────────────────────────────

def test_assign_players_all_any():
    ids = draw_daily_pool("2025-06-01")
    squares = assign_players_to_pool(ids, "2025-06-01", [])
    assert len(squares) == 16
    assert all(s["player_id"] is None for s in squares)
    assert all(s["player_name"] == "Any" for s in squares)


def test_assign_players_event_ids_preserved():
    ids = draw_daily_pool("2025-06-01")
    squares = assign_players_to_pool(ids, "2025-06-01", [])
    assert [s["event_id"] for s in squares] == ids


def test_assign_any_pool_size():
    ids = draw_daily_pool_league("2025-06-01")
    squares = assign_any_pool(ids)
    assert len(squares) == 24
    assert all(s["player_id"] is None for s in squares)


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call(["python", "-m", "pytest", __file__, "-v"]))
