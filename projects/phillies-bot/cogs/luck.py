"""
Cog: /luckiest and /unluckiest slash commands.

Luck is measured using xBA (estimated_ba_using_speedangle) from Statcast:
  - Hitter luck:   hits on batted balls with xBA < 0.250 (got hits they "shouldn't" have)
  - Hitter unluck: outs on batted balls with xBA > 0.500 (made outs they "shouldn't" have)
  - Pitcher luck:  outs on batted balls with xBA > 0.500 (got outs on balls that "should" be hits)
  - Pitcher unluck:hits on batted balls with xBA < 0.250 (allowed hits that "should" be outs)
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
    label_prefix: str,
    color: int,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if not players:
        embed.add_field(name="No data yet", value="Not enough batted-ball events this season.", inline=False)
        return embed
    for i, p in enumerate(players):
        embed.add_field(
            name=f"{_rank_emoji(i)}  {p['name']}",
            value=f"{label_prefix}: **{p['score']:.2f}**",
            inline=False,
        )
    embed.set_footer(text="Luck score based on xBA (expected batting average) via Statcast")
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
            description="Base hits on batted balls that usually result in outs (lowest xBA).",
            label_prefix="Luck score",
            color=PHILLIES_RED,
        )
        pitcher_embed = _build_embed(
            players=data["pitchers"],
            title=":four_leaf_clover: Luckiest Phillies Pitchers",
            description="Outs recorded on batted balls that usually result in hits (highest xBA).",
            label_prefix="Luck score",
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
            title=":crying_cat_face: Unluckiest Phillies Hitters",
            description="Outs on batted balls that usually result in hits (highest xBA).",
            label_prefix="Unluck score",
            color=PHILLIES_RED,
        )
        pitcher_embed = _build_embed(
            players=data["pitchers"],
            title=":crying_cat_face: Unluckiest Phillies Pitchers",
            description="Hits allowed on batted balls that usually result in outs (lowest xBA).",
            label_prefix="Unluck score",
            color=PHILLIES_BLUE,
        )

        await interaction.followup.send(embeds=[hitter_embed, pitcher_embed])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LuckCog(bot))
