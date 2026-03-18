"""
Cog: SP Grader — Philly Ace Rating (PAR) monitoring and leaderboard commands.

Polls MLB live data every 2 minutes and posts a PAR grade embed whenever a
Phillies starting pitcher exits. Also exposes /leaderboard and /par slash commands.

Required environment variable:
  SP_GRADER_CHANNEL_ID — channel ID where PAR grade reports are posted
"""
from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .monitor import GameMonitor
from .formatter import build_leaderboard_embed


class SPGraderCog(commands.Cog, name="SPGrader"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.monitor = GameMonitor()
        self._channel_id = int(os.environ.get("SP_GRADER_CHANNEL_ID", 0))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.sp_grader_loop.is_running():
            self.sp_grader_loop.start()

    @tasks.loop(minutes=2)
    async def sp_grader_loop(self) -> None:
        try:
            results = await self.monitor.check_games()
            channel = self.bot.get_channel(self._channel_id)
            if channel:
                for embed, file in results:
                    if file:
                        await channel.send(embed=embed, file=file)
                    else:
                        await channel.send(embed=embed)
        except Exception as exc:
            print(f"[spgrader] Loop error: {exc}")

    @sp_grader_loop.before_loop
    async def before_sp_grader_loop(self) -> None:
        await self.bot.wait_until_ready()

    @sp_grader_loop.error
    async def sp_grader_loop_error(self, error: Exception) -> None:
        print(f"[spgrader] Loop error (unhandled): {error}")

    # ── Slash Commands ────────────────────────────────────────────────────────

    @app_commands.command(
        name="leaderboard",
        description="View the Phillies Therapy PAR leaderboard"
    )
    @app_commands.describe(
        view="Choose between season averages or top individual performances"
    )
    @app_commands.choices(view=[
        app_commands.Choice(name="Season Averages", value="averages"),
        app_commands.Choice(name="Top Performances", value="individual"),
    ])
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        view: str = "averages",
    ) -> None:
        embed = build_leaderboard_embed(self.monitor.leaderboard, page=view)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="par",
        description="Look up a pitcher's season PAR stats"
    )
    @app_commands.describe(pitcher="Pitcher's name (partial match OK)")
    async def par(self, interaction: discord.Interaction, pitcher: str) -> None:
        await interaction.response.defer()

        lb = self.monitor.leaderboard
        records = [
            r for r in lb._records
            if pitcher.lower() in r.pitcher_name.lower()
        ]
        if not records:
            await interaction.followup.send(
                f"❌ No records found for **{pitcher}**.", ephemeral=True
            )
            return

        pitcher_id = records[0].pitcher_id
        name = records[0].pitcher_name
        avg = lb.get_pitcher_average(pitcher_id)
        games = lb.get_pitcher_games(pitcher_id)
        rank = lb.pitcher_rank(pitcher_id)
        best = max(r.score for r in records)
        worst = min(r.score for r in records)

        lines = [f"**{name}** — Season PAR Summary\n"]
        lines.append(
            f"🏟️ Avg PAR: **{avg:.1f}**  |  Games: **{games}**  |  Rank: **#{rank}**"
        )
        lines.append(f"⭐ Best: **{best:.1f}**  |  💀 Worst: **{worst:.1f}**\n")

        last_5 = sorted(records, key=lambda r: r.game_date, reverse=True)[:5]
        lines.append("**Last 5 Starts:**")
        for r in last_5:
            lines.append(
                f"• `{r.game_date}` vs **{r.opponent}** — "
                f"**{r.score:.1f}** PAR ({r.grade})  {r.ip} IP  {r.k}K/{r.bb}BB  {r.er}ER"
            )

        embed = discord.Embed(
            title=f"📊 {name} — PAR Profile",
            description="\n".join(lines),
            color=0xE81828,
        )
        embed.set_footer(text="Philly Ace Rating (PAR) · Phillies Therapy Bot")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SPGraderCog(bot))
