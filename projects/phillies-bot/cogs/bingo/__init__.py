"""
Phillies Bingo — Discord cog.

Commands:
  /bingo join        — Join today's bingo game (once per game day)
  /bingo check       — View your current board (ephemeral)
  /bingo leaderboard — Show top 5 season scores (public)

Background task polls live game data every 30 seconds, marks squares,
detects bingo wins, and posts public announcements to BINGO_CHANNEL_ID.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.mlb_data import (
    get_todays_phillies_games,
    get_live_game_data,
    get_phillies_roster_full,
    is_spring_training,
)

from .board import generate_layout, render_board_embed
from .events import (
    assign_players_to_pool,
    detect_events,
    detect_linescore_events,
    draw_daily_pool,
    get_phillies_lineup_ids,
    make_fingerprint,
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


class BingoCog(commands.Cog, name="Bingo"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._channel_id: int = int(os.environ.get("BINGO_CHANNEL_ID", 0) or 0)
        self._store = BingoStore()
        self._scores = ScoresStore()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.bingo_monitor.is_running():
            self.bingo_monitor.start()
        print("[bingo] Cog ready.")

    def cog_unload(self) -> None:
        self.bingo_monitor.cancel()

    # ── Slash command group ───────────────────────────────────────────────────

    bingo_group = app_commands.Group(
        name="bingo",
        description="Phillies Bingo game",
    )

    # /bingo join ─────────────────────────────────────────────────────────────

    @bingo_group.command(name="join", description="Join today's Phillies Bingo game")
    async def bingo_join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if is_spring_training():
            await interaction.followup.send(
                "⚾ Bingo is only available during the **regular season**. Check back on Opening Day!",
                ephemeral=True,
            )
            return

        today = date.today().isoformat()
        loop = asyncio.get_event_loop()
        games = await loop.run_in_executor(None, get_todays_phillies_games)

        if not games:
            await interaction.followup.send(
                "📅 No Phillies game scheduled today. Check back on the next game day!",
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)

        # Ensure today's state is initialised
        await self._ensure_game_day(loop, games)

        if self._store.is_game_over():
            await interaction.followup.send(
                "🏁 Today's Bingo game has already ended. See you next game day!",
                ephemeral=True,
            )
            return

        if self._store.has_player(uid):
            await interaction.followup.send(
                "You've already joined today's Bingo game! Use `/bingo check` to see your board.",
                ephemeral=True,
            )
            return

        pool = self._store.event_pool
        layout = generate_layout(len(pool), f"{uid}:{today}")
        self._store.add_player(uid, layout)

        # Check immediately in case events have already fired (late joiner)
        marked = self._store.get_marked_set()
        if marked:
            await self._check_player_win(uid, interaction.guild)

        self._scores.ensure_current_season(date.today().year)
        embed = make_join_confirm_embed(self._store.win_type, pool, today)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # /bingo check ────────────────────────────────────────────────────────────

    @bingo_group.command(name="check", description="View your current Bingo board")
    async def bingo_check(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        today = date.today().isoformat()

        if not self._store.is_today(today):
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
        player = self._store.get_player(uid)

        if player is None:
            await interaction.followup.send(
                "You haven't joined today's Bingo game yet. Use `/bingo join` to get your board!",
                ephemeral=True,
            )
            return

        pool = self._store.event_pool
        marked = self._store.get_marked_set()
        display_name = interaction.user.display_name

        embed = render_board_embed(
            layout=player["layout"],
            pool_squares=pool,
            marked_fingerprints=marked,
            display_name=display_name,
            win_type=self._store.win_type,
            bingo_achieved=player.get("bingo", False),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # /bingo leaderboard ──────────────────────────────────────────────────────

    @bingo_group.command(name="leaderboard", description="Show the season Bingo leaderboard")
    async def bingo_leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        year = date.today().year
        self._scores.ensure_current_season(year)

        entries = self._scores.get_top_n(5)
        embed = make_leaderboard_embed(entries, interaction.guild, year)
        await interaction.followup.send(embed=embed)

    # ── Background monitor ────────────────────────────────────────────────────

    @tasks.loop(seconds=30)
    async def bingo_monitor(self) -> None:
        try:
            await self._monitor_tick()
        except Exception as exc:
            print(f"[bingo] Monitor error: {exc}")

    @bingo_monitor.before_loop
    async def before_bingo_monitor(self) -> None:
        await self.bot.wait_until_ready()

    # ── Internal: monitor tick ────────────────────────────────────────────────

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

        # Process live games
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

        # Check for game-over condition
        if len(terminal_games) == len(games) and len(games) > 0:
            self._store.set_game_over()
            print(f"[bingo] All games finished for {today}. Bingo closed.")

    # ── Internal: ensure game day is initialised ──────────────────────────────

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

        # Fetch active roster for player assignment
        try:
            roster_raw = await loop.run_in_executor(None, get_phillies_roster_full)
            roster = [p for p in roster_raw if not p.get("on_il", True)]
        except Exception:
            roster = []

        pool_squares = assign_players_to_pool(event_ids, today, roster)
        self._store.reset_for_new_day(today, game_pks, win_type, pool_squares)
        print(f"[bingo] New game day: {today} | win type: {win_type} | {len(pool_squares)} squares")

    # ── Internal: process a live game feed ───────────────────────────────────

    async def _process_game(
        self,
        game_pk: int,
        feed: dict,
        today: str,
    ) -> None:
        # ── Lineup re-roll (once per day) ─────────────────────────────────────
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

        # ── Play-by-play events ───────────────────────────────────────────────
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

        # ── Linescore events (LEAD_CHANGE, EXTRA_INN, PHI_COMEBACK) ──────────
        prev_snap = self._store.get_linescore_snapshot(game_pk)
        ls_fingerprints, new_snap = detect_linescore_events(feed, prev_snap, marked, pool)
        for fp in ls_fingerprints:
            if self._store.mark_square(fp):
                new_fingerprints.append(fp)
                marked.add(fp)
        self._store.update_linescore_snapshot(game_pk, new_snap)

        # Persist if anything changed
        if new_fingerprints or new_plays:
            self._store.save()

        # ── Check for wins ────────────────────────────────────────────────────
        if new_fingerprints:
            for uid in list(self._store.players.keys()):
                if not self._store.is_winner(uid):
                    await self._check_player_win(uid, None)

    # ── Internal: check if a player has won ──────────────────────────────────

    async def _check_player_win(
        self,
        user_id: str,
        guild: Optional[discord.Guild],
    ) -> None:
        player = self._store.get_player(user_id)
        if player is None or player.get("bingo"):
            return

        pool = self._store.event_pool
        marked = self._store.get_marked_set()
        layout = player["layout"]
        marked_grid = build_marked_grid(layout, pool, marked)

        if not check_win(marked_grid, self._store.win_type):
            return

        # Award points
        place = self._store.get_winner_count() + 1
        if place > 10:
            return  # max 10 awards per day

        points = max(1, 11 - place)
        self._store.record_winner(user_id, place, points)

        today = self._store.game_date
        self._scores.ensure_current_season(date.today().year)
        self._scores.add_points(user_id, today, place, points)
        self._store.save()

        print(f"[bingo] {user_id} got BINGO! Place {place}, +{points} pts.")

        # Post public announcement
        channel = self.bot.get_channel(self._channel_id)
        if channel:
            # Resolve display name
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
                win_type=self._store.win_type,
                game_date=today,
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as exc:
                print(f"[bingo] Failed to post win announcement: {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BingoCog(bot))
