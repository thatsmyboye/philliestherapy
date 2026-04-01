"""
Cog: /sequence slash command.

Returns a PNG chart of an MLB pitcher's most effective 2-pitch sequences,
ranked by Whiff Rate, Chase Rate, Weak Contact Rate, or a composite Overall Score.

Data source: Baseball Savant / Statcast (via mlb_data.get_pitcher_statcast).
Sequence analysis: ported from sequencebaseball/pitch_viz.py.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.mlb_data import get_pitcher_statcast
from utils.player_lookup import resolve_player
from utils.sequence_calc import (
    analyze_pitch_sequences,
    create_sequence_chart_bytes,
    prepare_statcast_df,
)

PHILLIES_RED = 0xE81828

_HAND_CHOICES = [
    app_commands.Choice(name="vs RHH", value="R"),
    app_commands.Choice(name="vs LHH", value="L"),
]

_METRIC_CHOICES = [
    app_commands.Choice(name="Overall Score", value="overall"),
    app_commands.Choice(name="Whiff Rate",    value="whiff_rate"),
    app_commands.Choice(name="Chase Rate",    value="chase_rate"),
    app_commands.Choice(name="Weak Contact",  value="weak_contact"),
]

_METRIC_LABELS: dict[str, str] = {
    "overall":      "Overall Score",
    "whiff_rate":   "Whiff Rate",
    "chase_rate":   "Chase Rate",
    "weak_contact": "Weak Contact Rate",
}


class SequenceCog(commands.Cog, name="Sequence"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="sequence",
        description="Show a pitcher's most effective 2-pitch sequences this season.",
    )
    @app_commands.describe(
        pitcher_name="Pitcher's name (e.g. 'Zack Wheeler' or 'Wheeler')",
        batter_hand="Filter by batter handedness (default: all batters)",
        metric="Stat to rank sequences by (default: Overall Score)",
    )
    @app_commands.choices(batter_hand=_HAND_CHOICES, metric=_METRIC_CHOICES)
    async def sequence(
        self,
        interaction: discord.Interaction,
        pitcher_name: str,
        batter_hand: app_commands.Choice[str] | None = None,
        metric: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()

        # Resolve pitcher name → MLB ID
        mlbam_id, full_name, error = resolve_player(pitcher_name, require_pitcher=True)
        if error:
            await interaction.followup.send(f"**Error:** {error}", ephemeral=True)
            return

        # Fetch Statcast data (4-hour cache)
        rows = get_pitcher_statcast(mlbam_id)
        if not rows:
            await interaction.followup.send(
                f"No Statcast data found for **{full_name}** this season.",
                ephemeral=True,
            )
            return

        df = prepare_statcast_df(rows)

        hand_val = batter_hand.value if batter_hand else None
        metric_val = metric.value if metric else "overall"
        metric_label = _METRIC_LABELS.get(metric_val, "Overall Score")

        results_df = analyze_pitch_sequences(
            df,
            full_name,
            batter_hand=hand_val,
            success_metric=metric_val,
        )

        if results_df.empty:
            hand_str = f" vs {'RHH' if hand_val == 'R' else 'LHH'}" if hand_val else ""
            await interaction.followup.send(
                f"Not enough pitch sequence data for **{full_name}**{hand_str} "
                f"(need ≥ 20 occurrences per sequence).",
                ephemeral=True,
            )
            return

        buf = create_sequence_chart_bytes(results_df, full_name, hand_val, top_n=8)

        hand_str = f" vs {'RHH' if hand_val == 'R' else 'LHH'}" if hand_val else ""
        n_sequences = min(len(results_df), 8)
        season_year = df["game_date"].astype(str).str[:4].mode().iloc[0] if not df.empty else "current"

        embed = discord.Embed(
            title=f":baseball: {full_name} — Pitch Sequences{hand_str}",
            description=(
                f"Top {n_sequences} sequences ranked by **{metric_label}** · "
                f"{season_year} season · min 20 occurrences"
            ),
            color=PHILLIES_RED,
        )
        embed.set_image(url="attachment://sequences.png")
        embed.set_footer(text="Data via Baseball Savant / Statcast")

        await interaction.followup.send(
            embed=embed,
            file=discord.File(buf, filename="sequences.png"),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SequenceCog(bot))
