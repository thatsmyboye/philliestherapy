"""
Persistence layer for the Phillies Bingo game.

Two JSON files:
  data/bingo.json       — current game-day state (boards, marks, winners)
  data/bingo_scores.json — season-long cumulative scores
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BINGO_PATH = Path(__file__).parent.parent.parent / "data" / "bingo.json"
SCORES_PATH = Path(__file__).parent.parent.parent / "data" / "bingo_scores.json"

_BINGO_DEFAULT: dict = {
    "game_date": "",
    "game_pks": [],
    "win_type": "standard",
    "event_pool": [],           # list of square dicts
    "marked_squares": [],       # fingerprints that have been triggered
    "linescore_snapshots": {},  # game_pk_str → {phi_score, opp_score, inning}
    "last_play_counts": {},     # game_pk_str → int
    "lineups_checked": False,
    "game_over": False,
    "winners": [],              # [{user_id, place, points, timestamp}]
    "players": {},              # user_id_str → {layout, bingo, bingo_achieved_at}
}

_SCORES_DEFAULT: dict = {
    "season": 0,
    "scores": {},  # user_id_str → {total_points, games_played, wins, history}
}


# ---------------------------------------------------------------------------
# BingoStore — game-day state
# ---------------------------------------------------------------------------

class BingoStore:
    """Thin wrapper around a bingo game-day JSON file with atomic saves."""

    def __init__(self, path: Path = BINGO_PATH) -> None:
        self._path = path
        self._data = self._load()

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    data = json.load(f)
                for k, v in _BINGO_DEFAULT.items():
                    data.setdefault(k, copy.deepcopy(v))
                return data
            except Exception:
                pass
        return copy.deepcopy(_BINGO_DEFAULT)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self._path) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, str(self._path))

    # ── Game-day management ───────────────────────────────────────────────────

    def is_today(self, date_str: str) -> bool:
        return self._data.get("game_date") == date_str

    def reset_for_new_day(
        self,
        date_str: str,
        game_pks: list[int],
        win_type: str,
        event_pool: list[dict],
    ) -> None:
        self._data = copy.deepcopy(_BINGO_DEFAULT)
        self._data["game_date"] = date_str
        self._data["game_pks"] = game_pks
        self._data["win_type"] = win_type
        self._data["event_pool"] = event_pool
        self.save()

    # ── Event pool (mutable for re-rolls) ────────────────────────────────────

    @property
    def event_pool(self) -> list[dict]:
        return self._data["event_pool"]

    @event_pool.setter
    def event_pool(self, value: list[dict]) -> None:
        self._data["event_pool"] = value

    @property
    def win_type(self) -> str:
        return self._data.get("win_type", "standard")

    # ── Player management ────────────────────────────────────────────────────

    def has_player(self, user_id: str) -> bool:
        return str(user_id) in self._data["players"]

    def add_player(self, user_id: str, layout: list[list[int]]) -> None:
        self._data["players"][str(user_id)] = {
            "layout": layout,
            "bingo": False,
            "bingo_achieved_at": None,
        }
        self.save()

    def get_player(self, user_id: str) -> Optional[dict]:
        return self._data["players"].get(str(user_id))

    @property
    def players(self) -> dict:
        return self._data["players"]

    # ── Event marking ────────────────────────────────────────────────────────

    def mark_square(self, fingerprint: str) -> bool:
        """Mark a square fingerprint. Returns True if this is a new mark."""
        marked = self._data["marked_squares"]
        if fingerprint not in marked:
            marked.append(fingerprint)
            return True
        return False

    def get_marked_set(self) -> set[str]:
        return set(self._data.get("marked_squares", []))

    # ── Win management ───────────────────────────────────────────────────────

    def record_winner(self, user_id: str, place: int, points: int) -> None:
        uid = str(user_id)
        self._data["winners"].append({
            "user_id": uid,
            "place": place,
            "points": points,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if uid in self._data["players"]:
            self._data["players"][uid]["bingo"] = True
            self._data["players"][uid]["bingo_achieved_at"] = datetime.now(timezone.utc).isoformat()

    def get_winner_count(self) -> int:
        return len(self._data.get("winners", []))

    def is_winner(self, user_id: str) -> bool:
        uid = str(user_id)
        return any(w["user_id"] == uid for w in self._data.get("winners", []))

    def all_players_won(self) -> bool:
        if not self._data["players"]:
            return False
        return all(p["bingo"] for p in self._data["players"].values())

    def set_game_over(self) -> None:
        self._data["game_over"] = True
        self.save()

    def is_game_over(self) -> bool:
        return self._data.get("game_over", False)

    # ── Linescore snapshots ──────────────────────────────────────────────────

    def get_linescore_snapshot(self, game_pk: int) -> Optional[dict]:
        return self._data["linescore_snapshots"].get(str(game_pk))

    def update_linescore_snapshot(self, game_pk: int, snap: dict) -> None:
        self._data["linescore_snapshots"][str(game_pk)] = snap

    # ── Play count deduplication ─────────────────────────────────────────────

    def get_last_play_count(self, game_pk: int) -> int:
        return self._data["last_play_counts"].get(str(game_pk), 0)

    def set_last_play_count(self, game_pk: int, count: int) -> None:
        self._data["last_play_counts"][str(game_pk)] = count

    # ── Lineup re-roll tracking ──────────────────────────────────────────────

    @property
    def lineups_checked(self) -> bool:
        return self._data.get("lineups_checked", False)

    @lineups_checked.setter
    def lineups_checked(self, value: bool) -> None:
        self._data["lineups_checked"] = value

    # ── Misc ─────────────────────────────────────────────────────────────────

    @property
    def game_pks(self) -> list[int]:
        return self._data.get("game_pks", [])

    @property
    def game_date(self) -> str:
        return self._data.get("game_date", "")


# ---------------------------------------------------------------------------
# ScoresStore — season-long leaderboard
# ---------------------------------------------------------------------------

class ScoresStore:
    """Thin wrapper around a bingo season-scores JSON file with atomic saves."""

    def __init__(self, path: Path = SCORES_PATH) -> None:
        self._path = path
        self._data = self._load()

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    data = json.load(f)
                for k, v in _SCORES_DEFAULT.items():
                    data.setdefault(k, copy.deepcopy(v))
                return data
            except Exception:
                pass
        return copy.deepcopy(_SCORES_DEFAULT)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self._path) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, str(self._path))

    # ── Season management ────────────────────────────────────────────────────

    def ensure_current_season(self, year: int) -> None:
        """Reset scores if we've rolled into a new season year."""
        if self._data.get("season") != year:
            self._data["season"] = year
            self._data["scores"] = {}
            self.save()

    # ── Score updates ────────────────────────────────────────────────────────

    def add_points(self, user_id: str, date_str: str, place: int, points: int) -> None:
        uid = str(user_id)
        entry = self._data["scores"].setdefault(uid, {
            "total_points": 0,
            "games_played": 0,
            "wins": 0,
            "history": [],
        })
        entry["total_points"] += points
        entry["games_played"] += 1
        if place == 1:
            entry["wins"] += 1
        entry["history"].append({"date": date_str, "place": place, "points": points})
        self.save()

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_top_n(self, n: int = 5) -> list[dict]:
        """Return up to n entries sorted by total_points desc."""
        entries = [
            {"user_id": uid, **data}
            for uid, data in self._data["scores"].items()
        ]
        entries.sort(key=lambda e: e["total_points"], reverse=True)
        return entries[:n]

    def get_user_score(self, user_id: str) -> Optional[dict]:
        return self._data["scores"].get(str(user_id))
