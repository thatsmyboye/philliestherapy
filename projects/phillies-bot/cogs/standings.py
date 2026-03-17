"""
Cog: /standings slash command.

Displays division or wild card standings with W, L, GB, W%, and Pythagorean W%.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.mlb_data import (
    DIVISION_IDS,
    get_division_standings,
    get_wildcard_standings,
)

PHILLIES_RED = 0xE81828
PHILLIES_BLUE = 0x003087

_DIVISION_CHOICES = [
    app_commands.Choice(name=name, value=name)
    for name in [
        "NL East",
        "NL Central",
        "NL West",
        "AL East",
        "AL Central",
        "AL West",
        "Wild Card",
    ]
]


def _fmt_gb(gb: str) -> str:
    """Trim trailing '.0' from whole-number GB values for cleaner display."""
    try:
        f = float(gb)
        return str(int(f)) if f == int(f) else gb
    except (ValueError, TypeError):
        return gb


def _fmt_pct(pct: str) -> str:
    """Ensure winning percentage is formatted as '.xxx'."""
    try:
        return f"{float(pct):.3f}"
    except (ValueError, TypeError):
        return pct


def _fmt_pythag(pythag: float | None) -> str:
    if pythag is None:
        return "  N/A"
    return f"{pythag:.3f}"


def _build_standings_table(teams: list[dict]) -> str:
    """Return a monospace-formatted standings table string."""
    header = f"{'Team':<5} {'W':>3} {'L':>3} {'GB':>5} {'W%':>6} {'Pythag%':>8}"
    sep = "-" * len(header)
    rows = [header, sep]
    for t in teams:
        gb = _fmt_gb(t["gb"])
        pct = _fmt_pct(t["pct"])
        pythag = _fmt_pythag(t["pythag"])
        rows.append(
            f"{t['abbr']:<5} {t['w']:>3} {t['l']:>3} {gb:>5} {pct:>6} {pythag:>8}"
        )
    return "\n".join(rows)


def _division_embed(division: str, teams: list[dict]) -> discord.Embed:
    league = "NL" if division.startswith("NL") else "AL"
    color = PHILLIES_RED if league == "NL" else PHILLIES_BLUE

    embed = discord.Embed(
        title=f":baseball: {division} Standings",
        color=color,
    )

    if not teams:
        embed.description = "No standings data available."
        return embed

    table = _build_standings_table(teams)
    embed.description = f"```\n{table}\n```"
    embed.set_footer(text="Pythag% = RS^1.83 / (RS^1.83 + RA^1.83)  •  Data via MLB Stats API")
    return embed


def _wildcard_embed(league: str, teams: list[dict]) -> discord.Embed:
    color = PHILLIES_BLUE if league == "AL" else PHILLIES_RED
    league_full = "American League" if league == "AL" else "National League"

    embed = discord.Embed(
        title=f":baseball: {league_full} Wild Card Standings",
        color=color,
    )

    if not teams:
        embed.description = "No wild card data available."
        return embed

    table = _build_standings_table(teams)
    embed.description = f"```\n{table}\n```"
    embed.set_footer(text="GB = Wild Card games back  •  Pythag% = RS^1.83 / (RS^1.83 + RA^1.83)  •  Data via MLB Stats API")
    return embed


class StandingsCog(commands.Cog, name="Standings"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="standings",
        description="Show current MLB standings for a division or the Wild Card.",
    )
    @app_commands.describe(division="Division to display (or Wild Card for both leagues)")
    @app_commands.choices(division=_DIVISION_CHOICES)
    async def standings(
        self,
        interaction: discord.Interaction,
        division: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer()

        if division.value == "Wild Card":
            wc = get_wildcard_standings()
            al_embed = _wildcard_embed("AL", wc["AL"])
            nl_embed = _wildcard_embed("NL", wc["NL"])
            await interaction.followup.send(embeds=[al_embed, nl_embed])
        else:
            teams = get_division_standings(division.value)
            embed = _division_embed(division.value, teams)
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StandingsCog(bot))
