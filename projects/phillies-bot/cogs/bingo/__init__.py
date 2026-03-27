"""
Phillies + League Bingo — Discord cog.

Commands (channel-routed):
  /bingo join        — Join today's bingo game (once per game day)
  /bingo check       — View your current board (ephemeral)
  /bingo leaderboard — Show top 5 season scores (public)

The bot routes each command to the correct game variant based on the channel:
  BINGO_CHANNEL_ID       → Phillies bingo (Phillies-only events, roster-assigned squares)
  OTHER_BINGO_CHANNEL_ID → League bingo   (all non-Phillies games, all-"Any" squares)

Background tasks poll live game data every 30 seconds per variant, mark squares,
detect bingo wins, and post public announcements to the respective channel.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.mlb_data import (
    get_todays_phillies_games,
    get_todays_non_phillies_games,
    get_live_game_data,
    get_phillies_roster_full,
    is_spring_training,
)

from .board import generate_layout, render_board_embed
from .events import (
    assign_players_to_pool,
    assign_any_pool,
    detect_events,
    detect_events_league,
    detect_linescore_events,
    detect_linescore_events_league,
    draw_daily_pool,
    draw_daily_pool_league,
    get_phillies_lineup_ids,
    pick_win_type,
    reroll_scratched_players,
)
from .formatter import (
    make_join_confirm_embed,
    make_leaderboard_embed,
    make_win_announcement_embed,
)
from .storage import BingoStore, ScoresStore
from .win_checker import build_marked_grid, check_win

# Game statuses that mean the game is finished for today
_TERMINAL_STATUSES = {"Final", "Game Over", "Completed Early", "Postponed", "Cancelled"}

# Storage paths for the league variant
_DATA_DIR = Path(__file__).parent.parent.parent / "data"
LEAGUE_BINGO_PATH = _DATA_DIR / "bingo_league.json"
LEAGUE_SCORES_PATH = _DATA_DIR / "bingo_scores_league.json"


class BingoCog(commands.Cog, name="Bingo"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        # Phillies bingo
        self._channel_id: int = int(os.environ.get("BINGO_CHANNEL_ID", 0) or 0)
        self._store = BingoStore()
        self._scores = ScoresStore()

        # League bingo (all non-Phillies games)
        self._other_channel_id: int = int(os.environ.get("OTHER_BINGO_CHANNEL_ID", 0) or 0)
        self._league_store = BingoStore(LEAGUE_BINGO_PATH)
        self._league_scores = ScoresStore(LEAGUE_SCORES_PATH)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.bingo_monitor.is_running():
            self.bingo_monitor.start()
        if not self.league_monitor.is_running():
            self.league_monitor.start()
        print("[bingo] Cog ready.")

    def cog_unload(self) -> None:
        self.bingo_monitor.cancel()
        self.league_monitor.cancel()

    # ── Channel routing ───────────────────────────────────────────────────────

    def _effective_channel_id(self, interaction: discord.Interaction) -> int:
        """Return parent channel ID if invoked in a thread, otherwise the channel ID."""
        if isinstance(interaction.channel, discord.Thread):
            return interaction.channel.parent_id or interaction.channel_id
        return interaction.channel_id

    def _resolve_game(self, channel_id: int) -> Optional[tuple]:
        """
        Return (store, scores, announce_channel_id, variant) for the given channel,
        or None if the channel isn't configured for bingo.

        If neither BINGO_CHANNEL_ID nor OTHER_BINGO_CHANNEL_ID is set, bingo is
        allowed from any channel (Phillies mode), with announcements posted back
        to the command's own channel.
        """
        if self._channel_id and channel_id == self._channel_id:
            return (self._store, self._scores, self._channel_id, "phillies")
        if self._other_channel_id and channel_id == self._other_channel_id:
            return (self._league_store, self._league_scores, self._other_channel_id, "league")
        # Neither channel configured — allow from any channel (Phillies mode default).
        if not self._channel_id and not self._other_channel_id:
            return (self._store, self._scores, channel_id, "phillies")
        return None

    # ── Slash command group ───────────────────────────────────────────────────

    bingo_group = app_commands.Group(
        name="bingo",
        description="Bingo game",
    )

    # /bingo join ─────────────────────────────────────────────────────────────

    @bingo_group.command(name="join", description="Join today's Bingo game")
    async def bingo_join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        game_ctx = self._resolve_game(self._effective_channel_id(interaction))
        if game_ctx is None:
            await interaction.followup.send(
                "⚾ Bingo isn't available in this channel.",
                ephemeral=True,
            )
            return

        store, scores, announce_ch, variant = game_ctx

        if is_spring_training():
            await interaction.followup.send(
                "⚾ Bingo is only available during the **regular season**. Check back on Opening Day!",
                ephemeral=True,
            )
            return

        today = date.today().isoformat()
        loop = asyncio.get_event_loop()

        if variant == "phillies":
            games = await loop.run_in_executor(None, get_todays_phillies_games)
        else:
            games = await loop.run_in_executor(None, get_todays_non_phillies_games)

        if not games:
            msg = (
                "📅 No Phillies game scheduled today. Check back on the next game day!"
                if variant == "phillies"
                else "📅 No non-Phillies MLB games scheduled today. Check back later!"
            )
            await interaction.followup.send(msg, ephemeral=True)
            return

        uid = str(interaction.user.id)

        if variant == "phillies":
            await self._ensure_game_day(loop, games)
        else:
            await self._ensure_league_game_day(loop, games)

        if store.is_game_over():
            await interaction.followup.send(
                "🏁 Today's Bingo game has already ended. See you next game day!",
                ephemeral=True,
            )
            return

        if store.has_player(uid):
            await interaction.followup.send(
                "You've already joined today's Bingo game! Use `/bingo check` to see your board.",
                ephemeral=True,
            )
            return

        pool = store.event_pool
        layout = generate_layout(len(pool), f"{uid}:{today}")
        store.add_player(uid, layout)

        # Check immediately in case events have already fired (late joiner)
        marked = store.get_marked_set()
        if marked:
            variant_lbl = "League" if variant == "league" else "Phillies"
            await self._check_player_win(uid, interaction.guild, store, scores, announce_ch, variant_lbl)

        scores.ensure_current_season(date.today().year)
        variant_label = "League" if variant == "league" else "Phillies"
        embed = make_join_confirm_embed(store.win_type, pool, today, variant_label)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # /bingo check ────────────────────────────────────────────────────────────

    @bingo_group.command(name="check", description="View your current Bingo board")
    async def bingo_check(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        game_ctx = self._resolve_game(self._effective_channel_id(interaction))
        if game_ctx is None:
            await interaction.followup.send(
                "⚾ Bingo isn't available in this channel.",
                ephemeral=True,
            )
            return

        store, _scores, _ch, _variant = game_ctx
        today = date.today().isoformat()

        if not store.is_today(today):
            if is_spring_training():
                await interaction.followup.send(
                    "⚾ Bingo is only available during the regular season.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "📅 No active Bingo game today. Use `/bingo join` when a game is scheduled!",
                    ephemeral=True,
                )
            return

        uid = str(interaction.user.id)
        player = store.get_player(uid)

        if player is None:
            await interaction.followup.send(
                "You haven't joined today's Bingo game yet. Use `/bingo join` to get your board!",
                ephemeral=True,
            )
            return

        pool = store.event_pool
        marked = store.get_marked_set()
        display_name = interaction.user.display_name

        embed = render_board_embed(
            layout=player["layout"],
            pool_squares=pool,
            marked_fingerprints=marked,
            display_name=display_name,
            win_type=store.win_type,
            bingo_achieved=player.get("bingo", False),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # /bingo leaderboard ──────────────────────────────────────────────────────

    @bingo_group.command(name="leaderboard", description="Show the season Bingo leaderboard")
    async def bingo_leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        game_ctx = self._resolve_game(self._effective_channel_id(interaction))
        if game_ctx is None:
            await interaction.followup.send(
                "⚾ Bingo isn't available in this channel.",
            )
            return

        _store, scores, _ch, variant = game_ctx
        year = date.today().year
        scores.ensure_current_season(year)

        entries = scores.get_top_n(5)
        variant_label = "League" if variant == "league" else "Phillies"
        embed = make_leaderboard_embed(entries, interaction.guild, year, variant_label)
        await interaction.followup.send(embed=embed)

    # ── Background monitor: Phillies ──────────────────────────────────────────

    @tasks.loop(seconds=30)
    async def bingo_monitor(self) -> None:
        try:
            await self._monitor_tick()
        except Exception as exc:
            print(f"[bingo] Monitor error: {exc}")

    @bingo_monitor.before_loop
    async def before_bingo_monitor(self) -> None:
        await self.bot.wait_until_ready()

    # ── Background monitor: League ────────────────────────────────────────────

    @tasks.loop(seconds=30)
    async def league_monitor(self) -> None:
        try:
            await self._league_monitor_tick()
        except Exception as exc:
            print(f"[bingo:league] Monitor error: {exc}")

    @league_monitor.before_loop
    async def before_league_monitor(self) -> None:
        await self.bot.wait_until_ready()

    # ── Internal: Phillies monitor tick ──────────────────────────────────────

    async def _monitor_tick(self) -> None:
        if is_spring_training():
            return

        loop = asyncio.get_event_loop()
        games = await loop.run_in_executor(None, get_todays_phillies_games)

        if not games:
            return

        today = date.today().isoformat()
        await self._ensure_game_day(loop, games)

        if self._store.is_game_over():
            return

        if not self._store.players:
            return  # no one has joined yet

        live_games = [g for g in games if g.get("status") == "In Progress"]
        terminal_games = [g for g in games if g.get("status") in _TERMINAL_STATUSES]

        for game in live_games:
            game_pk = game.get("game_id")
            if not game_pk:
                continue
            try:
                feed = await loop.run_in_executor(None, get_live_game_data, game_pk)
                if feed:
                    await self._process_game(game_pk, feed, today)
            except Exception as exc:
                print(f"[bingo] Error processing game {game_pk}: {exc}")

        if len(terminal_games) == len(games) and len(games) > 0:
            self._store.set_game_over()
            print(f"[bingo] All Phillies games finished for {today}. Bingo closed.")

    # ── Internal: League monitor tick ─────────────────────────────────────────

    async def _league_monitor_tick(self) -> None:
        if is_spring_training():
            return

        loop = asyncio.get_event_loop()
        games = await loop.run_in_executor(None, get_todays_non_phillies_games)

        if not games:
            return

        today = date.today().isoformat()
        await self._ensure_league_game_day(loop, games)

        if self._league_store.is_game_over():
            return

        if not self._league_store.players:
            return  # no one has joined yet

        live_games = [g for g in games if g.get("status") == "In Progress"]
        terminal_games = [g for g in games if g.get("status") in _TERMINAL_STATUSES]

        for game in live_games:
            game_pk = game.get("game_id")
            if not game_pk:
                continue
            try:
                feed = await loop.run_in_executor(None, get_live_game_data, game_pk)
                if feed:
                    await self._process_league_game(game_pk, feed, today)
            except Exception as exc:
                print(f"[bingo:league] Error processing game {game_pk}: {exc}")

        if len(terminal_games) == len(games) and len(games) > 0:
            self._league_store.set_game_over()
            print(f"[bingo:league] All non-Phillies games finished for {today}. Bingo closed.")

    # ── Internal: ensure Phillies game day is initialised ─────────────────────

    async def _ensure_game_day(
        self,
        loop: asyncio.AbstractEventLoop,
        games: list[dict],
    ) -> None:
        today = date.today().isoformat()
        if self._store.is_today(today):
            return

        game_pks = [g["game_id"] for g in games if g.get("game_id")]
        win_type = pick_win_type(today)
        event_ids = draw_daily_pool(today)

        try:
            roster_raw = await loop.run_in_executor(None, get_phillies_roster_full)
            roster = [p for p in roster_raw if not p.get("on_il", True)]
        except Exception:
            roster = []

        pool_squares = assign_players_to_pool(event_ids, today, roster)
        self._store.reset_for_new_day(today, game_pks, win_type, pool_squares)
        print(f"[bingo] New game day: {today} | win type: {win_type} | {len(pool_squares)} squares")

    # ── Internal: ensure League game day is initialised ───────────────────────

    async def _ensure_league_game_day(
        self,
        loop: asyncio.AbstractEventLoop,
        games: list[dict],
    ) -> None:
        today = date.today().isoformat()
        if self._league_store.is_today(today):
            return

        game_pks = [g["game_id"] for g in games if g.get("game_id")]
        win_type = pick_win_type(today + ":league")
        event_ids = draw_daily_pool_league(today)

        pool_squares = assign_any_pool(event_ids)
        self._league_store.reset_for_new_day(today, game_pks, win_type, pool_squares)
        print(f"[bingo:league] New game day: {today} | win type: {win_type} | {len(pool_squares)} squares")

    # ── Internal: process a live Phillies game feed ───────────────────────────

    async def _process_game(
        self,
        game_pk: int,
        feed: dict,
        today: str,
    ) -> None:
        # Lineup re-roll (once per day)
        if not self._store.lineups_checked:
            lineup_ids = get_phillies_lineup_ids(feed)
            if lineup_ids:
                updated_pool = reroll_scratched_players(
                    self._store.event_pool,
                    lineup_ids,
                    today,
                )
                self._store.event_pool = updated_pool
                self._store.lineups_checked = True
                self._store.save()
                print(f"[bingo] Lineup re-roll complete for {today}.")

        pool = self._store.event_pool
        marked = self._store.get_marked_set()

        all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
        last_count = self._store.get_last_play_count(game_pk)
        new_plays = [p for p in all_plays[last_count:] if p.get("about", {}).get("isComplete")]

        new_fingerprints: list[str] = []
        for play in new_plays:
            triggered = detect_events(play, feed, pool, marked)
            for fp in triggered:
                if self._store.mark_square(fp):
                    new_fingerprints.append(fp)
                    marked.add(fp)

        if new_plays:
            self._store.set_last_play_count(game_pk, last_count + len(new_plays))

        prev_snap = self._store.get_linescore_snapshot(game_pk)
        ls_fingerprints, new_snap = detect_linescore_events(feed, prev_snap, marked, pool)
        for fp in ls_fingerprints:
            if self._store.mark_square(fp):
                new_fingerprints.append(fp)
                marked.add(fp)
        self._store.update_linescore_snapshot(game_pk, new_snap)

        if new_fingerprints or new_plays:
            self._store.save()

        if new_fingerprints:
            for uid in list(self._store.players.keys()):
                if not self._store.is_winner(uid):
                    await self._check_player_win(uid, None, self._store, self._scores, self._channel_id, "Phillies")

    # ── Internal: process a live League game feed ─────────────────────────────

    async def _process_league_game(
        self,
        game_pk: int,
        feed: dict,
        today: str,
    ) -> None:
        pool = self._league_store.event_pool
        marked = self._league_store.get_marked_set()

        all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
        last_count = self._league_store.get_last_play_count(game_pk)
        new_plays = [p for p in all_plays[last_count:] if p.get("about", {}).get("isComplete")]

        new_fingerprints: list[str] = []
        for play in new_plays:
            triggered = detect_events_league(play, pool, marked)
            for fp in triggered:
                if self._league_store.mark_square(fp):
                    new_fingerprints.append(fp)
                    marked.add(fp)

        if new_plays:
            self._league_store.set_last_play_count(game_pk, last_count + len(new_plays))

        prev_snap = self._league_store.get_linescore_snapshot(game_pk)
        ls_fingerprints, new_snap = detect_linescore_events_league(feed, prev_snap, marked, pool)
        for fp in ls_fingerprints:
            if self._league_store.mark_square(fp):
                new_fingerprints.append(fp)
                marked.add(fp)
        self._league_store.update_linescore_snapshot(game_pk, new_snap)

        if new_fingerprints or new_plays:
            self._league_store.save()

        if new_fingerprints:
            for uid in list(self._league_store.players.keys()):
                if not self._league_store.is_winner(uid):
                    await self._check_player_win(
                        uid, None,
                        self._league_store, self._league_scores, self._other_channel_id, "League",
                    )

    # ── Internal: check if a player has won ──────────────────────────────────

    async def _check_player_win(
        self,
        user_id: str,
        guild: Optional[discord.Guild],
        store: BingoStore,
        scores: ScoresStore,
        announce_channel_id: int,
        variant_label: str = "Phillies",
    ) -> None:
        player = store.get_player(user_id)
        if player is None or player.get("bingo"):
            return

        pool = store.event_pool
        marked = store.get_marked_set()
        layout = player["layout"]
        marked_grid = build_marked_grid(layout, pool, marked)

        if not check_win(marked_grid, store.win_type):
            return

        place = store.get_winner_count() + 1
        if place > 10:
            return  # max 10 awards per day

        points = max(1, 11 - place)
        store.record_winner(user_id, place, points)

        today = store.game_date
        scores.ensure_current_season(date.today().year)
        scores.add_points(user_id, today, place, points)
        store.save()

        print(f"[bingo] {user_id} got BINGO! Place {place}, +{points} pts.")

        channel = self.bot.get_channel(announce_channel_id)
        if channel:
            display_name = f"<@{user_id}>"
            resolved_guild = guild or (
                channel.guild if hasattr(channel, "guild") else None
            )
            if resolved_guild:
                member = resolved_guild.get_member(int(user_id))
                if member:
                    display_name = member.display_name

            embed = make_win_announcement_embed(
                display_name=display_name,
                place=place,
                points=points,
                win_type=store.win_type,
                game_date=today,
                variant_label=variant_label,
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as exc:
                print(f"[bingo] Failed to post win announcement: {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BingoCog(bot))
