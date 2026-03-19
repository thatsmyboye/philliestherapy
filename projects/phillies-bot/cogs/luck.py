"""
Cog: /luckiest and /unluckiest slash commands.

Luck is measured using a combined net score derived from xBA (estimated_ba_using_speedangle):

  Hitter score  = net hits added
    + hits on batted balls with xBA < 0.250  (lucky hits)
    − outs on batted balls with xBA > 0.500  (unlucky outs)

  Pitcher score = net hits saved
    + outs on batted balls with xBA > 0.500  (lucky outs / hits saved)
    − hits on batted balls with xBA < 0.250  (unlucky hits allowed)

Positive score → net lucky; negative score → net unlucky.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.mlb_data import get_phillies_luck

PHILLIES_RED = 0xE81828
PHILLIES_BLUE = 0x003087


def _rank_emoji(i: int) -> str:
    return ["🥇", "🥈", "🥉"][i]


def _build_embed(
    players: list[dict],
    title: str,
    description: str,
    label: str,
    color: int,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if not players:
        embed.add_field(name="No data yet", value="Not enough batted-ball events this season.", inline=False)
        return embed
    for i, p in enumerate(players):
        embed.add_field(
            name=f"{_rank_emoji(i)}  {p['name']}",
            value=f"{label}: **{p['score']:+.2f}**",
            inline=False,
        )
    embed.set_footer(text="Score = net hits added (hitters) or net hits saved (pitchers), weighted by xBA via Statcast")
    return embed


class LuckCog(commands.Cog, name="Luck"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /luckiest
    # ------------------------------------------------------------------
    @app_commands.command(
        name="luckiest",
        description="Top 3 luckiest Phillies hitters and pitchers this season (by xBA).",
    )
    async def luckiest(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        data = get_phillies_luck(lucky=True)

        hitter_embed = _build_embed(
            players=data["hitters"],
            title=":four_leaf_clover: Luckiest Phillies Hitters",
            description="Most cumulative hits added above expectation (xBA).",
            label="Hits added",
            color=PHILLIES_RED,
        )
        pitcher_embed = _build_embed(
            players=data["pitchers"],
            title=":four_leaf_clover: Luckiest Phillies Pitchers",
            description="Most cumulative hits saved above expectation (xBA).",
            label="Hits saved",
            color=PHILLIES_BLUE,
        )

        await interaction.followup.send(embeds=[hitter_embed, pitcher_embed])

    # ------------------------------------------------------------------
    # /unluckiest
    # ------------------------------------------------------------------
    @app_commands.command(
        name="unluckiest",
        description="Top 3 unluckiest Phillies hitters and pitchers this season (by xBA).",
    )
    async def unluckiest(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        data = get_phillies_luck(lucky=False)

        hitter_embed = _build_embed(
            players=data["hitters"],
            title=":no_entry_sign: Unluckiest Phillies Hitters",
            description="Most cumulative hits lost below expectation (xBA).",
            label="Hits added",
            color=PHILLIES_RED,
        )
        pitcher_embed = _build_embed(
            players=data["pitchers"],
            title=":no_entry_sign: Unluckiest Phillies Pitchers",
            description="Most cumulative hits allowed above expectation (xBA).",
            label="Hits saved",
            color=PHILLIES_BLUE,
        )

        await interaction.followup.send(embeds=[hitter_embed, pitcher_embed])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LuckCog(bot))
