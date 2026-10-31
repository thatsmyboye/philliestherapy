"""
Cog: /remember slash command.

Pulls a random Philadelphia Phillies player from a given season (or a random
season if none is specified) and shows their stats for that year.

  /remember           → picks a random year from 1883–current
  /remember year:1980 → shows a random player from the 1980 Phillies
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.mlb_data import get_phillies_season_player_stats

PHILLIES_RED = 0xE81828
PHILLIES_BLUE = 0x003087

PHILLIES_FIRST_SEASON = 1883
PHILLIES_LAST_SEASON = datetime.now().year

# How many random seasons to try before giving up (a random pick can land on a
# season with no data yet, e.g. the new calendar year before Opening Day).
RANDOM_YEAR_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------

def _has_hitting(stats: dict) -> bool:
    try:
        return int(stats.get("plateAppearances") or 0) > 0
    except (ValueError, TypeError):
        return False


def _has_pitching(stats: dict) -> bool:
    ip = str(stats.get("inningsPitched") or "0").strip()
    return ip not in ("0", "0.0", "", "-.--")


def _fmt_rate(val: object) -> str:
    """Format a rate stat (AVG/OBP/SLG/ERA) as a 3-decimal string without leading zero."""
    if val is None or str(val).strip() in ("", "-.--", "-"):
        return "N/A"
    try:
        f = float(val)
        s = f"{f:.3f}"
        # Remove leading zero: .300 not 0.300
        return s[1:] if s.startswith("0.") else s
    except (ValueError, TypeError):
        return str(val).strip() or "N/A"


def _fmt_era(val: object) -> str:
    """Format ERA as a 2-decimal string."""
    if val is None or str(val).strip() in ("", "-.--", "-"):
        return "N/A"
    try:
        return f"{float(val):.2f}"
    except (ValueError, TypeError):
        return str(val).strip() or "N/A"


def _int_stat(val: object) -> int:
    try:
        return int(val or 0)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Embed builder
# ---------------------------------------------------------------------------

def _build_embed(player: dict, year: int) -> discord.Embed:
    name = player["fullName"]
    position = player.get("position", "?")
    hitting = player.get("hitting", {})
    pitching = player.get("pitching", {})

    is_pitcher = _has_pitching(pitching) and not _has_hitting(hitting)
    color = PHILLIES_BLUE if is_pitcher else PHILLIES_RED

    embed = discord.Embed(
        title=f":baseball:  {name}",
        description=f"**{year} Philadelphia Phillies** · {position}",
        color=color,
    )

    if _has_hitting(hitting):
        pa = _int_stat(hitting.get("plateAppearances"))
        avg = _fmt_rate(hitting.get("avg"))
        obp = _fmt_rate(hitting.get("obp"))
        slg = _fmt_rate(hitting.get("slg"))
        hr = _int_stat(hitting.get("homeRuns"))
        rbi = _int_stat(hitting.get("rbi"))
        embed.add_field(
            name="Hitting",
            value=(
                f"**{pa} PA**  ·  {avg}/{obp}/{slg}\n"
                f"**{hr} HR**  ·  **{rbi} RBI**"
            ),
            inline=False,
        )

    if _has_pitching(pitching):
        ip = str(pitching.get("inningsPitched", "0.0"))
        era = _fmt_era(pitching.get("era"))
        k = _int_stat(pitching.get("strikeOuts"))
        bb = _int_stat(pitching.get("baseOnBalls"))
        embed.add_field(
            name="Pitching",
            value=(
                f"**{ip} IP**  ·  **{era} ERA**\n"
                f"**{k} K**  ·  **{bb} BB**"
            ),
            inline=False,
        )

    embed.set_footer(text=f"Stats with the Philadelphia Phillies · {year} season")
    return embed


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class RememberCog(commands.Cog, name="Remember"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="remember",
        description="Honor a random Phillies player from history (or a specific season).",
    )
    @app_commands.describe(
        year=f"Season year (1883–{PHILLIES_LAST_SEASON}). Leave blank for a random year.",
    )
    async def remember(
        self,
        interaction: discord.Interaction,
        year: Optional[app_commands.Range[int, PHILLIES_FIRST_SEASON, PHILLIES_LAST_SEASON]] = None,
    ) -> None:
        await interaction.response.defer()

        if year is not None:
            years = [year]
        else:
            years = random.sample(
                range(PHILLIES_FIRST_SEASON, PHILLIES_LAST_SEASON + 1),
                RANDOM_YEAR_ATTEMPTS,
            )

        loop = asyncio.get_running_loop()
        last_error: Optional[str] = None
        for chosen_year in years:
            # Blocking HTTP calls run off the event loop so the bot stays responsive.
            try:
                season_players = await loop.run_in_executor(
                    None, get_phillies_season_player_stats, chosen_year
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            candidates = [
                p for p in season_players
                if _has_hitting(p.get("hitting", {})) or _has_pitching(p.get("pitching", {}))
            ]
            if candidates:
                embed = _build_embed(random.choice(candidates), chosen_year)
                await interaction.followup.send(embed=embed)
                return

        if last_error is not None:
            # Discord message content is capped at 2000 characters.
            msg = f"Couldn't reach the MLB Stats API: `{last_error[:1500]}`"
        elif year is not None:
            msg = f"No stats found for the **{year} Phillies**. Try another year."
        else:
            msg = "Couldn't find Phillies stats right now. Try again in a bit."
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RememberCog(bot))
