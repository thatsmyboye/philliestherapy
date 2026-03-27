"""
Leaderboard — persists SP game scores to JSON and computes rankings.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional
from .config import Config

log = logging.getLogger("leaderboard")


@dataclass
class GameRecord:
    pitcher_name: str
    pitcher_id: int
    game_date: str
    opponent: str
    score: float
    grade: str
    ip: str
    k: int
    bb: int
    er: int
    h: int
    is_spring_training: bool = False


class Leaderboard:

    def __init__(self, filepath: str = None):
        self.filepath = filepath or Config.DATA_FILE
        self._records: list[GameRecord] = []
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    raw = json.load(f)
                self._records = [
                    GameRecord(**{**r, "is_spring_training": r.get("is_spring_training", False)})
                    for r in raw
                ]
                log.info(f"Leaderboard loaded: {len(self._records)} records")
            except Exception as e:
                log.error(f"Failed to load leaderboard: {e}")
                self._records = []

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump([asdict(r) for r in self._records], f, indent=2)
        except Exception as e:
            log.error(f"Failed to save leaderboard: {e}")

    def record(self, par_result) -> bool:
        """Add a game to the leaderboard. Returns False if duplicate."""
        from .scoring import PARResult
        result: PARResult = par_result
        data = result.data

        # Deduplicate by pitcher + date
        for r in self._records:
            if r.pitcher_id == result.pitcher_id and r.game_date == result.game_date:
                log.warning(f"Duplicate record: {result.pitcher_name} {result.game_date}")
                return False

        rec = GameRecord(
            pitcher_name=result.pitcher_name,
            pitcher_id=result.pitcher_id,
            game_date=result.game_date,
            opponent=result.opponent,
            score=result.total_score,
            grade=result.grade_letter,
            ip=data.innings_pitched_display,
            k=data.strikeouts,
            bb=data.walks,
            er=data.earned_runs,
            h=data.hits,
            is_spring_training=data.is_spring_training,
        )
        self._records.append(rec)
        self._save()
        log.info(f"Leaderboard saved: {result.pitcher_name} {result.game_date} → {result.total_score}")
        return True

    def record_or_update(self, par_result) -> None:
        """Add a game record, replacing any existing record for the same
        pitcher + date.  Used when re-grading a Final game to correct stats
        that were captured prematurely during a live exit-detection."""
        from .scoring import PARResult
        result: PARResult = par_result
        data = result.data

        rec = GameRecord(
            pitcher_name=result.pitcher_name,
            pitcher_id=result.pitcher_id,
            game_date=result.game_date,
            opponent=result.opponent,
            score=result.total_score,
            grade=result.grade_letter,
            ip=data.innings_pitched_display,
            k=data.strikeouts,
            bb=data.walks,
            er=data.earned_runs,
            h=data.hits,
            is_spring_training=data.is_spring_training,
        )

        for i, r in enumerate(self._records):
            if r.pitcher_id == result.pitcher_id and r.game_date == result.game_date:
                self._records[i] = rec
                self._save()
                log.info(
                    f"Leaderboard updated: {result.pitcher_name} {result.game_date}"
                    f" → {result.total_score} ({data.innings_pitched_display} IP)"
                )
                return

        self._records.append(rec)
        self._save()
        log.info(
            f"Leaderboard saved: {result.pitcher_name} {result.game_date}"
            f" → {result.total_score} ({data.innings_pitched_display} IP)"
        )

    def get_record(self, pitcher_id: int, game_date: str) -> Optional[GameRecord]:
        """Return the stored record for a pitcher on a given date, or None."""
        for r in self._records:
            if r.pitcher_id == pitcher_id and r.game_date == game_date:
                return r
        return None

    # ─── Queries ─────────────────────────────────────────────────────────────

    @property
    def _regular_season_records(self) -> list:
        """Records for regular season games only (excludes spring training)."""
        return [r for r in self._records if not r.is_spring_training]

    def get_pitcher_average(self, pitcher_id: int) -> Optional[float]:
        games = [r.score for r in self._regular_season_records if r.pitcher_id == pitcher_id]
        if not games:
            return None
        return round(sum(games) / len(games), 1)

    def get_pitcher_games(self, pitcher_id: int) -> int:
        return len([r for r in self._regular_season_records if r.pitcher_id == pitcher_id])

    def top_averages(self, n: int = 5, min_games: int = 1) -> list[dict]:
        """Top N pitchers by average PAR score."""
        by_pitcher: dict[int, list[float]] = {}
        names: dict[int, str] = {}
        for r in self._regular_season_records:
            by_pitcher.setdefault(r.pitcher_id, []).append(r.score)
            names[r.pitcher_id] = r.pitcher_name

        results = []
        for pid, scores in by_pitcher.items():
            if len(scores) >= min_games:
                avg = round(sum(scores) / len(scores), 1)
                results.append({
                    "pitcher_id": pid,
                    "name": names[pid],
                    "avg": avg,
                    "games": len(scores),
                    "best": round(max(scores), 1),
                })

        results.sort(key=lambda x: x["avg"], reverse=True)
        return results[:n]

    def top_individual(self, n: int = 5) -> list[GameRecord]:
        """Top N individual game performances (regular season only)."""
        sorted_records = sorted(self._regular_season_records, key=lambda r: r.score, reverse=True)
        return sorted_records[:n]

    def pitcher_rank(self, pitcher_id: int) -> Optional[int]:
        """Where does this pitcher rank on the average leaderboard?"""
        rankings = self.top_averages(n=999, min_games=1)
        for i, entry in enumerate(rankings, 1):
            if entry["pitcher_id"] == pitcher_id:
                return i
        return None
