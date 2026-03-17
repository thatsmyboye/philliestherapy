"""
Cog: Live game monitoring background loop.

Polls live Phillies game data every 30 seconds and posts alerts when:
  - A Phillies player sets a new season high (exit velo, pitch velo, game RBI)
  - A Phillies player sets a new career high for a counting stat in a season
    (only if they had ≥ 100 PA or ≥ 20 IP in at least one prior MLB season)
  - A Phillies player hits a career milestone (every 50 units up to configured max)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import statsapi

import utils.state as state_store
from utils.mlb_data import (
    CURRENT_SEASON,
    PHILLIES_TEAM_ID,
    get_phillies_roster,
    get_season_stats_by_year,
    get_career_stats,
    get_live_game_data,
    get_todays_phillies_games,
)

# ---------------------------------------------------------------------------
# Milestone thresholds (every 50 units up to max)
# ---------------------------------------------------------------------------
HIT_MILESTONES = list(range(50, 3001, 50))
HR_MILESTONES = list(range(50, 501, 50))
RBI_MILESTONES = list(range(50, 1501, 50))
WIN_MILESTONES = list(range(50, 301, 50))
K_MILESTONES = list(range(50, 3001, 50))
SAVE_MILESTONES = list(range(50, 301, 50))

# Career high tracking stats
HITTER_CAREER_HIGH_STATS = ["doubles", "triples", "homeRuns", "rbi", "stolenBases"]
PITCHER_CAREER_HIGH_STATS = ["wins", "strikeOuts", "saves"]

PHILLIES_RED = 0xE81828


class MonitorCog(commands.Cog, name="Monitor"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._state: dict = state_store.load()
        self._alerts_channel_id: int = int(os.environ.get("ALERTS_CHANNEL_ID", 0))
        # Map player_id → dict of player info (populated on ready)
        self._phillies_players: dict[int, dict] = {}
        # Career high eligibility cache: player_id → bool
        self._career_high_eligible: dict[int, bool] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self._init_player_data()
        if not self.monitor_games.is_running():
            self.monitor_games.start()

    async def _init_player_data(self) -> None:
        """
        Load career / season stats for all current Phillies players.
        Seeds state with career totals and determines career-high eligibility.
        """
        roster = get_phillies_roster()
        for player in roster:
            pid = player["id"]
            self._phillies_players[pid] = player

            # Career high eligibility: at least one prior season with 100+ PA or 20+ IP
            seasons = get_season_stats_by_year(pid)
            prior_hitting = [
                s for s in seasons
                if s.get("group") == "hitting"
                and int(s.get("season", 0)) < CURRENT_SEASON
                and int(s.get("plateAppearances", 0) or 0) >= 100
            ]
            prior_pitching = [
                s for s in seasons
                if s.get("group") == "pitching"
                and int(s.get("season", 0)) < CURRENT_SEASON
                and float(s.get("inningsPitched", 0) or 0) >= 20
            ]
            self._career_high_eligible[pid] = bool(prior_hitting or prior_pitching)

            # Seed career totals from career stats if not already tracked
            career = get_career_stats(pid)
            hitting = career.get("hitting", {})
            pitching = career.get("pitching", {})

            for stat_key, store_key in [
                ("hits", "hits"), ("homeRuns", "hr"), ("rbi", "rbi")
            ]:
                if state_store.get_career_total(self._state, pid, store_key) == 0:
                    val = int(hitting.get(stat_key, 0) or 0)
                    state_store.set_career_total(self._state, pid, store_key, val)

            for stat_key, store_key in [
                ("wins", "wins"), ("strikeOuts", "k"), ("saves", "saves")
            ]:
                if state_store.get_career_total(self._state, pid, store_key) == 0:
                    val = int(pitching.get(stat_key, 0) or 0)
                    state_store.set_career_total(self._state, pid, store_key, val)

            # Seed career highs (best single season) for eligible players
            if self._career_high_eligible[pid]:
                self._seed_career_highs(pid, seasons)

        state_store.save(self._state)

    def _seed_career_highs(self, pid: int, seasons: list[dict]) -> None:
        """Store the best prior-season value for each tracked stat."""
        for stat in HITTER_CAREER_HIGH_STATS:
            best = max(
                (int(s.get(stat, 0) or 0) for s in seasons
                 if s.get("group") == "hitting" and int(s.get("season", 0)) < CURRENT_SEASON),
                default=0,
            )
            existing = state_store.get_career_high(self._state, pid, stat)
            if best > existing:
                state_store.set_career_high(self._state, pid, stat, best)

        for stat in PITCHER_CAREER_HIGH_STATS:
            best = max(
                (int(s.get(stat, 0) or 0) for s in seasons
                 if s.get("group") == "pitching" and int(s.get("season", 0)) < CURRENT_SEASON),
                default=0,
            )
            existing = state_store.get_career_high(self._state, pid, stat)
            if best > existing:
                state_store.set_career_high(self._state, pid, stat, best)

    # ------------------------------------------------------------------
    # Main monitoring loop
    # ------------------------------------------------------------------
    @tasks.loop(seconds=30)
    async def monitor_games(self) -> None:
        # Only run between noon and midnight ET to avoid unnecessary polling
        now_hour = datetime.now(timezone.utc).hour
        # UTC noon = ~8 AM ET; UTC 5 AM = ~1 AM ET — covers any start time
        if now_hour < 12 or now_hour >= 5:
            pass  # Always attempt; statsapi.schedule returns nothing if no games

        games = get_todays_phillies_games()
        live_games = [g for g in games if g.get("status") == "In Progress"]

        for game in live_games:
            try:
                await self._check_game(game["game_id"])
            except Exception as exc:
                print(f"[monitor] Error checking game {game['game_id']}: {exc}")

        if live_games:
            state_store.save(self._state)

    @monitor_games.before_loop
    async def before_monitor(self) -> None:
        await self.bot.wait_until_ready()

    @monitor_games.error
    async def monitor_error(self, error: Exception) -> None:
        print(f"[monitor] Loop error: {error}")

    # ------------------------------------------------------------------
    # Per-game event processing
    # ------------------------------------------------------------------
    async def _check_game(self, game_pk: int) -> None:
        data = get_live_game_data(game_pk)
        if not data:
            return

        live_data = data.get("liveData", {})
        plays = live_data.get("plays", {}).get("allPlays", [])
        last_count = self._state["last_play_counts"].get(str(game_pk), 0)

        if len(plays) <= last_count:
            return

        new_plays = plays[last_count:]
        self._state["last_play_counts"][str(game_pk)] = len(plays)

        channel = self.bot.get_channel(self._alerts_channel_id)

        for play in new_plays:
            await self._process_play(play, channel)

    async def _process_play(self, play: dict, channel: discord.TextChannel | None) -> None:
        """
        Inspect a completed play for season highs, career highs, and milestones.
        """
        result = play.get("result", {})
        matchup = play.get("matchup", {})
        about = play.get("about", {})

        batter_id = matchup.get("batter", {}).get("id")
        pitcher_id = matchup.get("pitcher", {}).get("id")
        batter_name = matchup.get("batter", {}).get("fullName", "Unknown")
        pitcher_name = matchup.get("pitcher", {}).get("fullName", "Unknown")

        # Only alert for Phillies players
        phillies_ids = set(self._phillies_players.keys())

        # --- EXIT VELOCITY (Phillies batter) ---
        if batter_id in phillies_ids:
            hit_data = play.get("hitData", {})
            launch_speed = hit_data.get("launchSpeed")
            if launch_speed:
                launch_speed = float(launch_speed)
                prev_high = state_store.get_season_high(self._state, batter_id, "max_exit_velo")
                if launch_speed > prev_high:
                    state_store.set_season_high(self._state, batter_id, "max_exit_velo", launch_speed)
                    if prev_high > 0 and channel:
                        embed = _season_high_embed(
                            batter_name,
                            f"Season-high exit velocity: **{launch_speed} mph** (prev: {prev_high} mph)",
                        )
                        await channel.send(embed=embed)

            # --- GAME RBI ---
            rbi = int(result.get("rbi", 0))
            if rbi > 0:
                game_rbi_key = f"game_rbi_{about.get('gamePk', 0)}"
                current_game_rbi = state_store.get_season_high(self._state, batter_id, game_rbi_key) + rbi
                state_store.set_season_high(self._state, batter_id, game_rbi_key, current_game_rbi)
                prev_max = state_store.get_season_high(self._state, batter_id, "max_game_rbi")
                if current_game_rbi > prev_max:
                    state_store.set_season_high(self._state, batter_id, "max_game_rbi", current_game_rbi)
                    if prev_max > 0 and channel:
                        embed = _season_high_embed(
                            batter_name,
                            f"Season-high RBI in a game: **{int(current_game_rbi)}** (prev: {int(prev_max)})",
                        )
                        await channel.send(embed=embed)

            # --- CAREER MILESTONES (hitter) ---
            event = result.get("eventType", "")
            if event in ("single", "double", "triple", "home_run"):
                await self._check_hit_milestone(batter_id, batter_name, event, channel)

            if event == "home_run":
                await self._check_hr_milestone(batter_id, batter_name, channel)

            rbi_total_delta = int(result.get("rbi", 0))
            if rbi_total_delta:
                await self._check_rbi_milestone(batter_id, batter_name, rbi_total_delta, channel)

            # --- CAREER HIGHS (hitter) ---
            if self._career_high_eligible.get(batter_id):
                await self._check_hitter_career_highs(batter_id, batter_name, channel)

        # --- PITCH VELOCITY (Phillies pitcher) ---
        if pitcher_id in phillies_ids:
            for pitch_data in play.get("pitchIndex", []):
                pass  # pitch-level data lives in playEvents; processed below

            for pe in play.get("playEvents", []):
                if pe.get("isPitch"):
                    start_speed = pe.get("pitchData", {}).get("startSpeed")
                    if start_speed:
                        start_speed = float(start_speed)
                        prev_high = state_store.get_season_high(self._state, pitcher_id, "max_pitch_velo")
                        if start_speed > prev_high:
                            state_store.set_season_high(self._state, pitcher_id, "max_pitch_velo", start_speed)
                            if prev_high > 0 and channel:
                                embed = _season_high_embed(
                                    pitcher_name,
                                    f"Season-high pitch velocity: **{start_speed} mph** (prev: {prev_high} mph)",
                                )
                                await channel.send(embed=embed)

            # --- CAREER MILESTONES (pitcher) ---
            event = result.get("eventType", "")
            if event == "strikeout":
                await self._check_k_milestone(pitcher_id, pitcher_name, channel)

            # --- CAREER HIGHS (pitcher) ---
            if self._career_high_eligible.get(pitcher_id):
                await self._check_pitcher_career_highs(pitcher_id, pitcher_name, channel)

    # ------------------------------------------------------------------
    # Milestone helpers
    # ------------------------------------------------------------------
    async def _check_hit_milestone(
        self, pid: int, name: str, event: str, channel: discord.TextChannel | None
    ) -> None:
        current = state_store.get_career_total(self._state, pid, "hits") + 1
        state_store.set_career_total(self._state, pid, "hits", current)
        for threshold in HIT_MILESTONES:
            if current == threshold and not state_store.has_milestone(self._state, str(pid), "hits", threshold):
                state_store.record_milestone(self._state, str(pid), "hits", threshold)
                if channel:
                    embed = _milestone_embed(name, f"**{threshold:,} career hits!** :baseball:")
                    await channel.send(embed=embed)
                break

    async def _check_hr_milestone(
        self, pid: int, name: str, channel: discord.TextChannel | None
    ) -> None:
        current = state_store.get_career_total(self._state, pid, "hr") + 1
        state_store.set_career_total(self._state, pid, "hr", current)
        for threshold in HR_MILESTONES:
            if current == threshold and not state_store.has_milestone(self._state, str(pid), "hr", threshold):
                state_store.record_milestone(self._state, str(pid), "hr", threshold)
                if channel:
                    embed = _milestone_embed(name, f"**{threshold} career home runs!** :boom:")
                    await channel.send(embed=embed)
                break

    async def _check_rbi_milestone(
        self, pid: int, name: str, rbi_delta: int, channel: discord.TextChannel | None
    ) -> None:
        prev = state_store.get_career_total(self._state, pid, "rbi")
        current = prev + rbi_delta
        state_store.set_career_total(self._state, pid, "rbi", current)
        for threshold in RBI_MILESTONES:
            if prev < threshold <= current and not state_store.has_milestone(self._state, str(pid), "rbi", threshold):
                state_store.record_milestone(self._state, str(pid), "rbi", threshold)
                if channel:
                    embed = _milestone_embed(name, f"**{threshold:,} career RBI!** :trophy:")
                    await channel.send(embed=embed)

    async def _check_k_milestone(
        self, pid: int, name: str, channel: discord.TextChannel | None
    ) -> None:
        current = state_store.get_career_total(self._state, pid, "k") + 1
        state_store.set_career_total(self._state, pid, "k", current)
        for threshold in K_MILESTONES:
            if current == threshold and not state_store.has_milestone(self._state, str(pid), "k", threshold):
                state_store.record_milestone(self._state, str(pid), "k", threshold)
                if channel:
                    embed = _milestone_embed(name, f"**{threshold:,} career strikeouts!** :fire:")
                    await channel.send(embed=embed)
                break

    # ------------------------------------------------------------------
    # Career high helpers
    # ------------------------------------------------------------------
    async def _check_hitter_career_highs(
        self, pid: int, name: str, channel: discord.TextChannel | None
    ) -> None:
        """
        Compare current season totals against career highs for hitting stats.
        Requires a live season-stat refresh — we use statsapi for this.
        """
        try:
            data = statsapi.player_stat_data(pid, group="[hitting]", type="season")
            season_stats = {}
            for group in data.get("stats", []):
                if group.get("group", {}).get("displayName", "").lower() == "hitting":
                    season_stats = group.get("stats", {})
                    break
        except Exception:
            return

        for stat in HITTER_CAREER_HIGH_STATS:
            current_val = int(season_stats.get(stat, 0) or 0)
            prev_high = state_store.get_career_high(self._state, pid, stat)
            if current_val > prev_high and prev_high > 0:
                state_store.set_career_high(self._state, pid, stat, current_val)
                if channel:
                    label = stat.replace("homeRuns", "HR").replace("rbi", "RBI").replace(
                        "stolenBases", "SB").replace("doubles", "2B").replace("triples", "3B")
                    embed = _career_high_embed(
                        name,
                        f"New career-high in **{label}** this season: **{current_val}** (prev: {prev_high})",
                    )
                    await channel.send(embed=embed)

    async def _check_pitcher_career_highs(
        self, pid: int, name: str, channel: discord.TextChannel | None
    ) -> None:
        try:
            data = statsapi.player_stat_data(pid, group="[pitching]", type="season")
            season_stats = {}
            for group in data.get("stats", []):
                if group.get("group", {}).get("displayName", "").lower() == "pitching":
                    season_stats = group.get("stats", {})
                    break
        except Exception:
            return

        for stat in PITCHER_CAREER_HIGH_STATS:
            current_val = int(season_stats.get(stat, 0) or 0)
            prev_high = state_store.get_career_high(self._state, pid, stat)
            if current_val > prev_high and prev_high > 0:
                state_store.set_career_high(self._state, pid, stat, current_val)
                if channel:
                    label = stat.replace("strikeOuts", "K").replace("wins", "W").replace("saves", "SV")
                    embed = _career_high_embed(
                        name,
                        f"New career-high in **{label}** this season: **{current_val}** (prev: {prev_high})",
                    )
                    await channel.send(embed=embed)


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------

def _season_high_embed(player_name: str, detail: str) -> discord.Embed:
    return discord.Embed(
        title=f":bar_chart: Season High — {player_name}",
        description=detail,
        color=0xE81828,
    ).set_footer(text="Phillies Bot • Live Game Alert")


def _career_high_embed(player_name: str, detail: str) -> discord.Embed:
    return discord.Embed(
        title=f":star: Career High — {player_name}",
        description=detail,
        color=0xFFD700,
    ).set_footer(text="Phillies Bot • Live Game Alert")


def _milestone_embed(player_name: str, detail: str) -> discord.Embed:
    return discord.Embed(
        title=f":confetti_ball: Career Milestone — {player_name}",
        description=detail,
        color=0x00B000,
    ).set_footer(text="Phillies Bot • Live Game Alert")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonitorCog(bot))
