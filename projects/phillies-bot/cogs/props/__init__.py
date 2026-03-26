"""
Live stat props competition cog.

Provides:
  /prop add    — add a game or season prop (player, stat, line)
  /prop remove — remove a prop
  /prop list   — show all props with current live values
  /prop clear  — remove all props

A 30-second monitoring loop fetches live game data and season stats for every
tracked player, posts an alert embed when a player crosses their line, and
maintains an updating scoreboard message in PROPS_CHANNEL_ID.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.mlb_data import CURRENT_SEASON, get_live_game_data, get_todays_phillies_games
from utils.player_lookup import resolve_player

from .formatter import make_alert_embed, make_scoreboard_embed
from .stats import SEASON_ONLY_STATS, STAT_DEFINITIONS, get_game_stats, get_season_stats
from .storage import PropsStore


class PropsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._channel_id: int = int(os.environ.get("PROPS_CHANNEL_ID", 0))
        self._store = PropsStore()
        self.monitor_props.start()

    def cog_unload(self) -> None:
        self.monitor_props.cancel()

    # ── Monitoring loop ───────────────────────────────────────────────────────

    @tasks.loop(seconds=30)
    async def monitor_props(self) -> None:
        if not self._channel_id:
            return
        props = self._store.props
        if not props:
            return

        channel = self.bot.get_channel(self._channel_id)
        if not channel:
            return

        loop = asyncio.get_event_loop()

        # Fetch today's live games once
        games = await loop.run_in_executor(None, get_todays_phillies_games)
        live_games = [g for g in games if g.get("status") == "In Progress"]

        # Build game_pk → live feed map
        feeds: dict[int, dict] = {}
        for g in live_games:
            game_pk = g.get("game_id")
            if game_pk:
                feed = await loop.run_in_executor(None, get_live_game_data, game_pk)
                if feed:
                    feeds[game_pk] = feed

        # Evaluate every prop
        prop_values: list[dict] = []

        for prop in props:
            player_id = prop["player_id"]
            stat = prop["stat"]
            line = prop["line"]
            scope = prop["scope"]

            current_value: Optional[float] = None
            game_pk_hit: Optional[int] = None

            if scope == "game":
                for game_pk, feed in feeds.items():
                    val = get_game_stats(feed, player_id, stat)
                    if val is not None:
                        current_value = val
                        game_pk_hit = game_pk
                        break
            else:  # season
                current_value = await loop.run_in_executor(
                    None, lambda: get_season_stats(player_id, stat)
                )

            # Determine over/under status
            if current_value is None:
                status = "no_data"
            elif current_value > line:
                status = "over"
            elif current_value < line:
                status = "under"
            else:
                status = "push"

            prop_values.append(
                {
                    "prop": prop,
                    "current_value": current_value,
                    "status": status,
                    "game_pk": game_pk_hit,
                }
            )

            # Fire alert the first time a player goes over
            if status == "over":
                if scope == "game" and game_pk_hit:
                    fingerprint = f"{player_id}:{stat}:game:{game_pk_hit}"
                elif scope == "season":
                    fingerprint = f"{player_id}:{stat}:season:{CURRENT_SEASON}"
                else:
                    fingerprint = None

                if fingerprint and not self._store.has_alert_posted(fingerprint):
                    game_info = self._extract_game_info(feeds, game_pk_hit)
                    embed = make_alert_embed(prop, current_value, game_info)
                    await channel.send(embed=embed)
                    self._store.record_alert_posted(fingerprint)

        # Update (or create) the scoreboard message
        await self._update_scoreboard(channel, prop_values)

    @monitor_props.before_loop
    async def _before_monitor(self) -> None:
        await self.bot.wait_until_ready()

    @monitor_props.error
    async def _monitor_error(self, error: Exception) -> None:
        print(f"[props] Monitor loop error: {error}")

    # ── Scoreboard helpers ────────────────────────────────────────────────────

    async def _update_scoreboard(
        self, channel: discord.TextChannel, prop_values: list[dict]
    ) -> None:
        embed = make_scoreboard_embed(prop_values)
        msg_id = self._store.scoreboard_message_id

        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden):
                self._store.scoreboard_message_id = None

        new_msg = await channel.send(embed=embed)
        self._store.scoreboard_message_id = new_msg.id

    @staticmethod
    def _extract_game_info(feeds: dict, game_pk: Optional[int]) -> Optional[dict]:
        """Pull away/home abbreviations and current inning from a live feed."""
        if not game_pk or game_pk not in feeds:
            return None
        feed = feeds[game_pk]
        game_data = feed.get("gameData", {})
        linescore = feed.get("liveData", {}).get("linescore", {})
        return {
            "away": game_data.get("teams", {}).get("away", {}).get("abbreviation", "?"),
            "home": game_data.get("teams", {}).get("home", {}).get("abbreviation", "?"),
            "inning": linescore.get("currentInning", "?"),
            "inning_half": linescore.get("inningHalf", ""),
        }

    # ── Slash command group ───────────────────────────────────────────────────

    prop_group = app_commands.Group(
        name="prop",
        description="Manage the server's over/under stat props competition",
    )

    @prop_group.command(name="add", description="Add a stat prop to track")
    @app_commands.describe(
        player="Player name — e.g. 'Bryce Harper' or 'Wheeler'",
        stat="Stat to track",
        line="The over/under line — e.g. 1.5",
        scope="Per-game prop or full-season prop",
    )
    @app_commands.choices(
        stat=[
            app_commands.Choice(name=v["display"], value=k)
            for k, v in STAT_DEFINITIONS.items()
        ],
        scope=[
            app_commands.Choice(name="Game", value="game"),
            app_commands.Choice(name="Season", value="season"),
        ],
    )
    async def prop_add(
        self,
        interaction: discord.Interaction,
        player: str,
        stat: str,
        line: float,
        scope: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        # Validate scope for season-only stats
        if stat in SEASON_ONLY_STATS and scope == "game":
            stat_display = STAT_DEFINITIONS[stat]["display"]
            await interaction.followup.send(
                f"❌ **{stat_display}** can only be tracked as a season prop.",
                ephemeral=True,
            )
            return

        # Resolve player name → MLBAM ID
        loop = asyncio.get_event_loop()
        player_id, full_name, error = await loop.run_in_executor(
            None, lambda: resolve_player(player)
        )
        if error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        # Duplicate check
        for p in self._store.props:
            if p["player_id"] == player_id and p["stat"] == stat and p["scope"] == scope:
                stat_display = STAT_DEFINITIONS[stat]["display"]
                await interaction.followup.send(
                    f"❌ A **{scope}** prop for **{full_name}** — {stat_display} already exists.",
                    ephemeral=True,
                )
                return

        prop = {
            "id": str(uuid.uuid4())[:8],
            "player_name": full_name,
            "player_id": player_id,
            "stat": stat,
            "line": line,
            "scope": scope,
            "created_by": interaction.user.name,
            "created_at": date.today().isoformat(),
        }
        self._store.add_prop(prop)

        stat_display = STAT_DEFINITIONS[stat]["display"]
        await interaction.followup.send(
            f"✅ Added **{scope}** prop: **{full_name}** — {stat_display} O/U **{line}**",
            ephemeral=True,
        )

    @prop_group.command(name="remove", description="Remove a stat prop")
    @app_commands.describe(
        player="Player name",
        stat="Stat type",
        scope="Game or season prop",
    )
    @app_commands.choices(
        stat=[
            app_commands.Choice(name=v["display"], value=k)
            for k, v in STAT_DEFINITIONS.items()
        ],
        scope=[
            app_commands.Choice(name="Game", value="game"),
            app_commands.Choice(name="Season", value="season"),
        ],
    )
    async def prop_remove(
        self,
        interaction: discord.Interaction,
        player: str,
        stat: str,
        scope: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        loop = asyncio.get_event_loop()
        player_id, full_name, error = await loop.run_in_executor(
            None, lambda: resolve_player(player)
        )
        if error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        to_remove = [
            p
            for p in self._store.props
            if p["player_id"] == player_id and p["stat"] == stat and p["scope"] == scope
        ]
        for p in to_remove:
            self._store.remove_prop(p["id"])

        stat_display = STAT_DEFINITIONS[stat]["display"]
        if to_remove:
            await interaction.followup.send(
                f"✅ Removed **{scope}** prop: **{full_name}** — {stat_display}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ No matching prop found for **{full_name}** — {stat_display} ({scope}).",
                ephemeral=True,
            )

    @prop_group.command(name="list", description="Show all configured props and their current status")
    async def prop_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        props = self._store.props
        if not props:
            await interaction.followup.send(
                "No props configured yet. Use `/prop add` to get started.", ephemeral=True
            )
            return

        loop = asyncio.get_event_loop()
        games = await loop.run_in_executor(None, get_todays_phillies_games)
        live_games = [g for g in games if g.get("status") == "In Progress"]

        feeds: dict[int, dict] = {}
        for g in live_games:
            game_pk = g.get("game_id")
            if game_pk:
                feed = await loop.run_in_executor(None, get_live_game_data, game_pk)
                if feed:
                    feeds[game_pk] = feed

        prop_values: list[dict] = []
        for prop in props:
            current_value: Optional[float] = None
            if prop["scope"] == "game":
                for feed in feeds.values():
                    val = get_game_stats(feed, prop["player_id"], prop["stat"])
                    if val is not None:
                        current_value = val
                        break
            else:
                current_value = await loop.run_in_executor(
                    None, lambda: get_season_stats(prop["player_id"], prop["stat"])
                )

            if current_value is None:
                status = "no_data"
            elif current_value > prop["line"]:
                status = "over"
            elif current_value < prop["line"]:
                status = "under"
            else:
                status = "push"

            prop_values.append(
                {"prop": prop, "current_value": current_value, "status": status, "game_pk": None}
            )

        embed = make_scoreboard_embed(prop_values)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @prop_group.command(name="clear", description="Remove all configured props")
    @app_commands.describe(confirm="Type 'yes' to confirm clearing all props")
    async def prop_clear(self, interaction: discord.Interaction, confirm: str) -> None:
        if confirm.lower() != "yes":
            await interaction.response.send_message(
                "❌ Pass `confirm: yes` to clear all props.", ephemeral=True
            )
            return
        self._store.clear_props()
        await interaction.response.send_message("✅ All props cleared.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PropsCog(bot))
