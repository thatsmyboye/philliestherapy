"""
Slash command extension for leaderboard queries.
Attach to the bot via bot.py with cog loading.
"""

import discord
from discord import app_commands
from discord.ext import commands
from leaderboard import Leaderboard
from formatter import build_leaderboard_embed


class LeaderboardCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.lb = Leaderboard()

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
    ):
        embed = build_leaderboard_embed(self.lb, page=view)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="par",
        description="Look up a pitcher's season PAR stats"
    )
    @app_commands.describe(pitcher="Pitcher's name (partial match OK)")
    async def par(self, interaction: discord.Interaction, pitcher: str):
        records = [
            r for r in self.lb._records
            if pitcher.lower() in r.pitcher_name.lower()
        ]
        if not records:
            await interaction.response.send_message(
                f"❌ No records found for **{pitcher}**.", ephemeral=True
            )
            return

        pitcher_id = records[0].pitcher_id
        name = records[0].pitcher_name
        avg = self.lb.get_pitcher_average(pitcher_id)
        games = self.lb.get_pitcher_games(pitcher_id)
        rank = self.lb.pitcher_rank(pitcher_id)
        best = max(r.score for r in records)
        worst = min(r.score for r in records)

        lines = [f"**{name}** — Season PAR Summary\n"]
        lines.append(f"🏟️ Avg PAR: **{avg:.1f}**  |  Games: **{games}**  |  Rank: **#{rank}**")
        lines.append(f"⭐ Best: **{best:.1f}**  |  💀 Worst: **{worst:.1f}**\n")

        # Last 5 games
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
            color=0xE81828
        )
        embed.set_footer(text="Philly Ace Rating (PAR) · Phillies Therapy Bot")
        await interaction.response.send_message(embed=embed)
