"""
Cog: /topvelopitch and /topvelohit slash commands.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.mlb_data import (
    PITCH_TYPE_LABELS,
    PITCH_LABEL_TO_CODE,
    top_pitch_velos,
    top_exit_velos,
)
from utils.player_lookup import resolve_player

# Build the Choice list once at import time so it's available for the decorator.
_PITCH_CHOICES = [
    app_commands.Choice(name=label, value=label)
    for label in PITCH_TYPE_LABELS.values()
]

# Phillies red embed color
PHILLIES_RED = 0xE81828


class VelocityCog(commands.Cog, name="Velocity"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /topvelopitch
    # ------------------------------------------------------------------
    @app_commands.command(
        name="topvelopitch",
        description="Get a pitcher's three fastest pitches of a given type this season.",
    )
    @app_commands.describe(
        pitcher_name="Pitcher's name (e.g. 'Zack Wheeler' or 'Wheeler')",
        pitch_type="Pitch type to search",
    )
    @app_commands.choices(pitch_type=_PITCH_CHOICES)
    async def topvelopitch(
        self,
        interaction: discord.Interaction,
        pitcher_name: str,
        pitch_type: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer()

        mlbam_id, full_name, error = resolve_player(pitcher_name, require_pitcher=True)
        if error:
            await interaction.followup.send(f"**Error:** {error}", ephemeral=True)
            return

        pitch_code = PITCH_LABEL_TO_CODE.get(pitch_type.value)
        if not pitch_code:
            await interaction.followup.send(
                f"**Error:** Unknown pitch type '{pitch_type.value}'.", ephemeral=True
            )
            return

        pitches = top_pitch_velos(mlbam_id, pitch_code)
        if not pitches:
            await interaction.followup.send(
                f"No **{pitch_type.value}** data found for **{full_name}** this season.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f":baseball: {full_name} — Top {len(pitches)} {pitch_type.value}s",
            description=f"Fastest **{pitch_type.value}** pitches thrown this season.",
            color=PHILLIES_RED,
        )
        medals = ["🥇", "🥈", "🥉"]
        for i, p in enumerate(pitches):
            count_str = f"{p['balls']}-{p['strikes']}"
            embed.add_field(
                name=f"{medals[i]}  {p['speed']} mph",
                value=f"Date: {p['date']}  |  Count: {count_str}  |  Inning: {p['inning']}\n_{p['description'].replace('_', ' ').title()}_",
                inline=False,
            )
        embed.set_footer(text="Data via Baseball Savant / Statcast")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /topvelohit
    # ------------------------------------------------------------------
    @app_commands.command(
        name="topvelohit",
        description="Get a hitter's three hardest-hit balls in play this season.",
    )
    @app_commands.describe(
        hitter_name="Hitter's name (e.g. 'Bryce Harper' or 'Harper')",
    )
    async def topvelohit(
        self,
        interaction: discord.Interaction,
        hitter_name: str,
    ) -> None:
        await interaction.response.defer()

        mlbam_id, full_name, error = resolve_player(hitter_name, require_hitter=True)
        if error:
            await interaction.followup.send(f"**Error:** {error}", ephemeral=True)
            return

        hits = top_exit_velos(mlbam_id)
        if not hits:
            await interaction.followup.send(
                f"No batted-ball data found for **{full_name}** this season.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f":bat: {full_name} — Top {len(hits)} Exit Velocities",
            description="Hardest-hit balls in play this season (including home runs).",
            color=PHILLIES_RED,
        )
        medals = ["🥇", "🥈", "🥉"]
        for i, h in enumerate(hits):
            distance_str = f"  |  {h['hit_distance']} ft" if h["hit_distance"] else ""
            embed.add_field(
                name=f"{medals[i]}  {h['exit_velo']} mph — {h['event']}",
                value=f"Launch Angle: {h['launch_angle']}°{distance_str}  |  Date: {h['date']}",
                inline=False,
            )
        embed.set_footer(text="Data via Baseball Savant / Statcast")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VelocityCog(bot))
