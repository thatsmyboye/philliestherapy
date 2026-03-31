"""
Cog: SP Grader — Pitcher Ace Rating (PAR) monitoring and leaderboard commands.

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
from datetime import date as _date
from .formatter import build_leaderboard_embed, build_league_embed


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
        view="Choose a leaderboard view",
        date="Date for MLB league view (YYYY-MM-DD). Defaults to today. Only used with 'League Leaders'.",
    )
    @app_commands.choices(view=[
        app_commands.Choice(name="Season Averages", value="averages"),
        app_commands.Choice(name="Top Performances", value="individual"),
        app_commands.Choice(name="Recent Games", value="cal"),
        app_commands.Choice(name="League Leaders", value="league"),
    ])
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        view: str = "averages",
        date: str = None,
    ) -> None:
        if view == "league":
            await interaction.response.defer()
            season = _date.today().year
            if date:
                # Validate date format
                try:
                    from datetime import datetime as _dt
                    _dt.strptime(date, "%Y-%m-%d")
                except ValueError:
                    await interaction.followup.send(
                        "❌ Invalid date format. Use YYYY-MM-DD (e.g. `2026-04-15`).",
                        ephemeral=True,
                    )
                    return
                starters = await self.monitor.api.get_league_starters_by_date(date)
                embed = build_league_embed(starters, date_label=date, is_season=False)
            else:
                leaders = await self.monitor.api.get_league_season_pitching_leaders(season)
                embed = build_league_embed(leaders, date_label=str(season), is_season=True)
            await interaction.followup.send(embed=embed)
        else:
            embed = build_leaderboard_embed(self.monitor.leaderboard, page=view)
            await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="par",
        description="Look up a pitcher's season PAR stats"
    )
    @app_commands.describe(pitcher="Pitcher name (select from starters with 1+ games)")
    async def par(self, interaction: discord.Interaction, pitcher: str) -> None:
        await interaction.response.defer()

        lb = self.monitor.leaderboard
        records = [
            r for r in lb._regular_season_records
            if pitcher.lower() in r.pitcher_name.lower()
        ]

        # Check if pitcher is currently being tracked in a live game
        live_section = None
        for tg in self.monitor.tracked.values():
            if tg.sp_name and pitcher.lower() in tg.sp_name.lower() and not tg.reported:
                try:
                    feed = await self.monitor.api.get_live_feed(tg.game_pk)
                    bs_stats = self.monitor._extract_pitcher_stats_from_feed(feed, tg.sp_id)
                    if bs_stats:
                        from .scoring import PitcherGameData, grade_pitcher
                        from datetime import date
                        game_info = feed.get("gameData", {})
                        home_team = game_info.get("teams", {}).get("home", {}).get("abbreviation", "???")
                        away_team = game_info.get("teams", {}).get("away", {}).get("abbreviation", "???")
                        opponent = home_team if tg.phillies_side == "away" else away_team
                        ip_str = bs_stats.get("inningsPitched", "0.0")
                        outs = self.monitor._ip_to_outs(ip_str)
                        live_data = PitcherGameData(
                            name=tg.sp_name,
                            pitcher_id=tg.sp_id,
                            game_date=date.today().isoformat(),
                            opponent=opponent,
                            home_away=tg.phillies_side or "home",
                            outs_recorded=outs,
                            hits=bs_stats.get("hits", 0),
                            runs=bs_stats.get("runs", 0),
                            earned_runs=bs_stats.get("earnedRuns", 0),
                            walks=bs_stats.get("baseOnBalls", 0),
                            strikeouts=bs_stats.get("strikeOuts", 0),
                            home_runs=bs_stats.get("homeRuns", 0),
                            batters_faced=bs_stats.get("battersFaced", 0),
                            pitches_thrown=bs_stats.get("pitchesThrown", 0),
                            strikes_thrown=bs_stats.get("strikes", 0),
                        )
                        live_result = grade_pitcher(live_data)
                        status = "pitching" if not tg.sp_exited else "exited"
                        live_section = (
                            f"🔴 **LIVE** ({status}) — vs {opponent}\n"
                            f"{live_data.innings_pitched_display} IP  "
                            f"{live_data.hits}H  {live_data.earned_runs}ER  "
                            f"{live_data.walks}BB  {live_data.strikeouts}K  "
                            f"{live_data.pitches_thrown}P\n"
                            f"Live PAR: **{live_result.total_score:.1f}** ({live_result.grade_letter})"
                        )
                except Exception:
                    pass
                break

        if not records and not live_section:
            await interaction.followup.send(
                f"❌ No records found for **{pitcher}**.", ephemeral=True
            )
            return

        lines = []
        if records:
            pitcher_id = records[0].pitcher_id
            name = records[0].pitcher_name
            avg = lb.get_pitcher_average(pitcher_id)
            games = lb.get_pitcher_games(pitcher_id)
            rank = lb.pitcher_rank(pitcher_id)
            best = max(r.score for r in records)
            worst = min(r.score for r in records)

            lines.append(f"**{name}** — Season PAR Summary\n")
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
        else:
            # Pitcher found only in live tracking, no history yet
            tg_name = next(
                (tg.sp_name for tg in self.monitor.tracked.values()
                 if tg.sp_name and pitcher.lower() in tg.sp_name.lower()),
                pitcher
            )
            lines.append(f"**{tg_name}** — no completed starts recorded this season.\n")

        if live_section:
            lines.append(f"\n{live_section}")

        embed = discord.Embed(
            title=f"📊 {records[0].pitcher_name if records else pitcher} — PAR Profile",
            description="\n".join(lines),
            color=0xE81828,
        )
        embed.set_footer(text="Pitcher Ace Rating (PAR) · Phillies Therapy Bot")
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="backfill",
        description="[Admin] Backfill PAR data for a specific past date"
    )
    @app_commands.describe(date="Date to backfill (YYYY-MM-DD)")
    async def backfill(self, interaction: discord.Interaction, date: str) -> None:
        await interaction.response.defer(ephemeral=True)

        app_info = await self.bot.application_info()
        if interaction.user.id != app_info.owner.id:
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return

        try:
            from datetime import datetime as _dt
            _dt.strptime(date, "%Y-%m-%d")
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid date format. Use YYYY-MM-DD (e.g. `2026-03-27`).",
                ephemeral=True,
            )
            return

        results = await self.monitor.backfill_game_date(date)
        if not results:
            await interaction.followup.send(
                f"No completed Phillies games found for **{date}**.", ephemeral=True
            )
            return

        channel = self.bot.get_channel(self._channel_id)
        for embed, file in results:
            if channel:
                if file:
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)

        await interaction.followup.send(
            f"✅ Backfilled **{len(results)}** game(s) for **{date}**.", ephemeral=True
        )

    @par.autocomplete("pitcher")
    async def par_pitcher_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Return pitchers with 1+ recorded starts, sorted A-Z by last name."""
        seen: dict[int, str] = {}
        for r in self.monitor.leaderboard._regular_season_records:
            seen[r.pitcher_id] = r.pitcher_name

        def _last_name(name: str) -> str:
            parts = name.strip().split()
            return parts[-1].lower() if parts else name.lower()

        pitchers = sorted(seen.values(), key=_last_name)
        if current:
            pitchers = [p for p in pitchers if current.lower() in p.lower()]

        return [app_commands.Choice(name=p, value=p) for p in pitchers[:25]]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SPGraderCog(bot))
