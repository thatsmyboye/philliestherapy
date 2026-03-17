"""
GameMonitor — polls MLB live feed, detects Phillies SP exit,
waits for inning to complete, then fires the grader.
"""

import asyncio
import logging
from datetime import date, datetime
from typing import Optional
import discord

from SPgrader.config import Config
from SPgrader.mlb_api import MLBClient
from SPgrader.scoring import PitcherGameData, grade_pitcher, PARResult
from SPgrader.formatter import build_embed
from SPgrader.leaderboard import Leaderboard

log = logging.getLogger("monitor")


class TrackedGame:
    """Holds state for one Phillies game being monitored."""

    def __init__(self, game_pk: int, game_date: str):
        self.game_pk = game_pk
        self.game_date = game_date
        self.sp_id: Optional[int] = None
        self.sp_name: Optional[str] = None
        self.sp_exited: bool = False        # starter has been replaced
        self.inning_complete: bool = False  # inning after exit has finished
        self.reported: bool = False         # embed already posted
        self.inning_at_exit: Optional[int] = None
        self.half_at_exit: Optional[str] = None   # "top" | "bottom"
        self.phillies_side: Optional[str] = None  # "home" | "away"


class GameMonitor:

    def __init__(self):
        self.api = MLBClient()
        self.leaderboard = Leaderboard()
        self.tracked: dict[int, TrackedGame] = {}   # game_pk → TrackedGame

    async def check_games(self) -> list[tuple[discord.Embed, Optional[discord.File]]]:
        """Called every 2 minutes. Returns list of (embed, file) to post."""
        results = []
        games = await self.api.get_todays_schedule(Config.PHILLIES_TEAM_ID)

        for game in games:
            game_pk = game["gamePk"]
            status = game.get("status", {}).get("abstractGameState", "")

            # Skip games not yet live or already final
            if status not in ("Live", "Final"):
                continue

            if game_pk not in self.tracked:
                tg = TrackedGame(game_pk, date.today().isoformat())
                self.tracked[game_pk] = tg

            tg = self.tracked[game_pk]
            if tg.reported:
                continue

            result = await self._process_game(tg, game, status)
            if result:
                results.append(result)

        return results

    async def _process_game(
        self,
        tg: TrackedGame,
        game_data: dict,
        status: str,
    ) -> Optional[tuple[discord.Embed, Optional[discord.File]]]:
        try:
            feed = await self.api.get_live_feed(tg.game_pk)
        except Exception as e:
            log.warning(f"Live feed fetch failed for {tg.game_pk}: {e}")
            return None

        game_info = feed.get("gameData", {})
        live_data = feed.get("liveData", {})
        linescore = live_data.get("linescore", {})

        # Identify which side the Phillies are on
        if tg.phillies_side is None:
            home_id = game_info.get("teams", {}).get("home", {}).get("id")
            tg.phillies_side = "home" if home_id == Config.PHILLIES_TEAM_ID else "away"

        # Identify the starting pitcher if not yet set
        if tg.sp_id is None:
            sp = self._get_starting_pitcher(feed, tg.phillies_side)
            if sp:
                tg.sp_id, tg.sp_name = sp
                log.info(f"Game {tg.game_pk}: Tracking SP {tg.sp_name} (ID {tg.sp_id})")

        if tg.sp_id is None:
            return None  # Game may not have started

        # ── Check if starter has been replaced ────────────────────────────────
        if not tg.sp_exited:
            current_pitcher_id = self._get_current_pitcher(feed, tg.phillies_side)
            if current_pitcher_id and current_pitcher_id != tg.sp_id:
                log.info(
                    f"Game {tg.game_pk}: SP {tg.sp_name} exited, "
                    f"replaced by pitcher ID {current_pitcher_id}"
                )
                tg.sp_exited = True
                tg.inning_at_exit = linescore.get("currentInning")
                tg.half_at_exit = linescore.get("inningHalf", "").lower()  # "Top"/"Bottom"

        # ── Wait for inning to complete ────────────────────────────────────────
        if tg.sp_exited and not tg.inning_complete:
            tg.inning_complete = self._is_inning_complete(
                linescore, tg.inning_at_exit, tg.half_at_exit, status
            )
            if not tg.inning_complete:
                log.debug(f"Game {tg.game_pk}: Waiting for inning to complete...")
                return None

        if not tg.sp_exited:
            # Game ended with SP still in — treat game final as trigger
            if status == "Final":
                tg.sp_exited = True
                tg.inning_complete = True
            else:
                return None

        if not tg.inning_complete:
            return None

        # ── Build pitcher data & grade ─────────────────────────────────────────
        log.info(f"Game {tg.game_pk}: Building PAR for {tg.sp_name}")
        pitcher_data = await self._build_pitcher_data(tg, feed, game_info)
        if pitcher_data is None:
            return None

        result = grade_pitcher(pitcher_data)

        # Save to leaderboard
        self.leaderboard.record(result)

        tg.reported = True
        embed = build_embed(result, self.leaderboard)
        return embed, None

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _get_starting_pitcher(self, feed: dict, side: str) -> Optional[tuple[int, str]]:
        """Return (id, name) of the starting pitcher for the given side."""
        boxscore = feed.get("liveData", {}).get("boxscore", {})
        pitchers = boxscore.get("teams", {}).get(side, {}).get("pitchers", [])
        players = boxscore.get("teams", {}).get(side, {}).get("players", {})

        if not pitchers:
            return None

        starter_id = pitchers[0]
        key = f"ID{starter_id}"
        name = players.get(key, {}).get("person", {}).get("fullName", "Unknown")
        return starter_id, name

    def _get_current_pitcher(self, feed: dict, side: str) -> Optional[int]:
        """Return the ID of the current pitcher on the mound for the given side."""
        linescore = feed.get("liveData", {}).get("linescore", {})
        defense_side = "home" if side == "away" else "away"
        # The current pitcher pitches from the opposite dugout
        current = linescore.get("defense" if side == "away" else "offense", {})
        # Actually use the correct field: pitcher is in defense for the *other* team
        defense = linescore.get("defense", {})
        offense = linescore.get("offense", {})

        # Phillies pitching: they're pitching when opponent is batting
        # If Phillies = "home", they pitch in top innings (away bats)
        current_inning_half = feed.get("liveData", {}).get("linescore", {}).get("inningHalf", "")

        if side == "home" and current_inning_half.lower() == "top":
            return defense.get("pitcher", {}).get("id")
        elif side == "away" and current_inning_half.lower() == "bottom":
            return defense.get("pitcher", {}).get("id")
        else:
            # Between-inning check via boxscore order
            boxscore = feed.get("liveData", {}).get("boxscore", {})
            pitchers = boxscore.get("teams", {}).get(side, {}).get("pitchers", [])
            return pitchers[-1] if pitchers else None

    def _is_inning_complete(
        self,
        linescore: dict,
        inning_at_exit: Optional[int],
        half_at_exit: Optional[str],
        game_status: str,
    ) -> bool:
        """
        Return True when the half-inning in which the SP exited has ended.
        """
        if game_status == "Final":
            return True

        current_inning = linescore.get("currentInning", 0)
        current_half = linescore.get("inningHalf", "").lower()

        if inning_at_exit is None:
            return False

        # A new half-inning has started (or a new full inning)
        if current_inning > inning_at_exit:
            return True
        if current_inning == inning_at_exit:
            # Same inning — check half
            if half_at_exit == "top" and current_half == "bottom":
                return True
            if half_at_exit == "bottom" and current_half in ("top", ""):
                # Bottom of inning X → Top of inning X+1
                return True
        return False

    async def _build_pitcher_data(
        self, tg: TrackedGame, feed: dict, game_info: dict
    ) -> Optional[PitcherGameData]:
        """Assemble a PitcherGameData from boxscore + Statcast."""
        # Boxscore stats
        bs_stats = await self.api.get_pitcher_game_stats(tg.game_pk, tg.sp_id)
        if bs_stats is None:
            log.warning(f"Could not get boxscore stats for {tg.sp_name}")
            return None

        # Parse IP string ("5.2" = 5 full innings + 2 outs = 17 outs)
        ip_str = bs_stats.get("inningsPitched", "0.0")
        outs = self._ip_to_outs(ip_str)

        # Opponent abbreviation
        home_team = game_info.get("teams", {}).get("home", {}).get("abbreviation", "???")
        away_team = game_info.get("teams", {}).get("away", {}).get("abbreviation", "???")
        opponent = home_team if tg.phillies_side == "away" else away_team

        data = PitcherGameData(
            name=tg.sp_name,
            pitcher_id=tg.sp_id,
            game_date=tg.game_date,
            opponent=opponent,
            home_away=tg.phillies_side,
            outs_recorded=outs,
            hits=bs_stats.get("hits", 0),
            runs=bs_stats.get("runs", 0),
            earned_runs=bs_stats.get("earnedRuns", 0),
            walks=bs_stats.get("baseOnBalls", 0),
            strikeouts=bs_stats.get("strikeOuts", 0),
            home_runs=bs_stats.get("homeRuns", 0),
            batters_faced=bs_stats.get("battersFaced", 0),
            pitches_thrown=bs_stats.get("pitchesThrown", 0),
            strikes_thrown=bs_stats.get("strikes", 0),
        )

        # Statcast enrichment (best-effort)
        try:
            pitches = await self.api.get_statcast_game(tg.game_pk, tg.sp_id)
            self._enrich_from_statcast(data, pitches)
        except Exception as e:
            log.warning(f"Statcast enrichment failed: {e}")
            # Fall back to play-by-play for CSW
            try:
                plays = await self.api.get_pitcher_plays(tg.game_pk, tg.sp_id)
                self._enrich_from_plays(data, plays)
            except Exception as e2:
                log.warning(f"Play-by-play enrichment also failed: {e2}")

        return data

    def _ip_to_outs(self, ip_str: str) -> int:
        """Convert '5.2' → 17 outs, '6.0' → 18 outs."""
        try:
            parts = str(ip_str).split(".")
            full_innings = int(parts[0])
            partial = int(parts[1]) if len(parts) > 1 else 0
            return full_innings * 3 + partial
        except (ValueError, IndexError):
            return 0

    def _enrich_from_statcast(self, data: PitcherGameData, pitches: list[dict]):
        """Parse Statcast CSV rows into data fields."""
        called = 0
        swinging = 0
        evs = []
        las = []

        for p in pitches:
            desc = p.get("description", "")
            ptype = p.get("type", "")

            if desc == "called_strike":
                called += 1
            elif desc in ("swinging_strike", "swinging_strike_blocked", "foul_tip"):
                swinging += 1

            # BIP exit velocity / launch angle
            ev_raw = p.get("launch_speed", "")
            la_raw = p.get("launch_angle", "")
            try:
                ev = float(ev_raw)
                la = float(la_raw)
                if ev > 0:
                    evs.append(ev)
                    las.append(la)
            except (ValueError, TypeError):
                pass

        data.called_strikes = called
        data.swinging_strikes = swinging
        data.exit_velocities = evs
        data.launch_angles = las

    def _enrich_from_plays(self, data: PitcherGameData, plays: list[dict]):
        """Fallback: extract CSW from play-by-play events."""
        called = 0
        swinging = 0
        for play in plays:
            for event in play.get("playEvents", []):
                details = event.get("details", {})
                desc = details.get("description", "")
                if "Called Strike" in desc:
                    called += 1
                elif "Swinging Strike" in desc or "Foul Tip" in desc:
                    swinging += 1
        data.called_strikes = called
        data.swinging_strikes = swinging
