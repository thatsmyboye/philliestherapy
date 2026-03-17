"""
Discord embed builder for SP performance reports.
"""

import discord
from datetime import datetime
from SPgrader.scoring import PARResult, ComponentScore
from SPgrader.leaderboard import Leaderboard, GameRecord

# Phillies colors
PHILLIES_RED = 0xE81828
PHILLIES_CREAM = 0xFFFBF0
DARK_BG = 0x1A1A2E

COMPONENT_LABELS = {
    "efficiency":          ("⏱️", "Efficiency",       "Innings Pitched"),
    "run_prevention":      ("🛡️", "Run Prevention",   "Earned Runs"),
    "strikeouts":          ("🔥", "Strikeouts",       "K's"),
    "walk_control":        ("🎯", "Walk Control",     "BB's"),
    "strike_ball_ratio":   ("⚡", "Strike/Ball %",   "Strike %"),
    "csw":                 ("🌀", "CSW%",             "CSW %"),
    "batted_ball_quality": ("💥", "Batted Ball Qual.","Avg Exit Velo"),
}


def _par_bar(score: float, length: int = 10) -> str:
    """Return a text progress bar for the given score (0–100)."""
    filled = round(score / 100 * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"`{bar}`"


def _score_color(score: float) -> int:
    """Map PAR score to a Discord embed color."""
    if score >= 90:
        return 0xFFD700   # Gold
    if score >= 80:
        return 0x00C851   # Green
    if score >= 65:
        return 0x33B5E5   # Blue
    if score >= 50:
        return 0xFF8800   # Orange
    if score >= 35:
        return 0xFF4444   # Red
    return 0x4A4A4A       # Gray


def build_embed(result: PARResult, lb: Leaderboard) -> discord.Embed:
    """Build the main SP report embed."""
    data = result.data
    color = _score_color(result.total_score)

    # Header
    home_away_str = "vs" if data.home_away == "home" else "@"
    title = (
        f"{result.grade_emoji}  {result.pitcher_name}  |  "
        f"PHI {home_away_str} {data.opponent}  ·  {data.game_date}"
    )

    embed = discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Philly Ace Rating (PAR) · Phillies Therapy Bot")

    # ── Box Score Line ────────────────────────────────────────────────────────
    box = (
        f"```\n"
        f"{'IP':<6} {'H':<5} {'R':<5} {'ER':<5} {'BB':<5} {'K':<5} "
        f"{'P-S':<10} {'CSW%':<8}\n"
        f"{data.innings_pitched_display:<6} {data.hits:<5} {data.runs:<5} "
        f"{data.earned_runs:<5} {data.walks:<5} {data.strikeouts:<5} "
        f"{data.pitches_thrown}-{data.strikes_thrown:<8} "
        f"{data.csw_pct * 100:.1f}%\n"
        f"```"
    )
    embed.add_field(name="📋 Box Score", value=box, inline=False)

    # ── PAR Score ─────────────────────────────────────────────────────────────
    bar = _par_bar(result.total_score, 12)
    par_str = (
        f"**{result.total_score:.1f} / 100** — Grade: **{result.grade_letter}**\n"
        f"{bar}  {result.grade_emoji}"
    )
    embed.add_field(name="🏟️ Philly Ace Rating (PAR)", value=par_str, inline=False)

    # ── Component Breakdown ───────────────────────────────────────────────────
    breakdown_lines = []
    for comp in result.components:
        icon, label, raw_label = COMPONENT_LABELS.get(comp.name, ("▪️", comp.name, ""))
        raw_display = _format_raw(comp.name, comp.raw_value)
        mini_bar = _par_bar(comp.score, 6)
        breakdown_lines.append(
            f"{icon} **{label}** {mini_bar} `{comp.score:.0f}/100`  ·  {raw_label}: {raw_display}"
            f"  _(×{comp.weight}%)_"
        )
    embed.add_field(
        name="📊 Component Breakdown",
        value="\n".join(breakdown_lines),
        inline=False,
    )

    # ── Batted Ball note if EV available ──────────────────────────────────────
    if data.avg_exit_velocity:
        la_str = f"{data.avg_launch_angle:.1f}°" if data.avg_launch_angle else "N/A"
        embed.add_field(
            name="📡 Statcast",
            value=(
                f"Avg Exit Velo: **{data.avg_exit_velocity:.1f} mph**  ·  "
                f"Avg Launch Angle: **{la_str}**  ·  "
                f"BIP tracked: **{len(data.exit_velocities)}**"
            ),
            inline=False,
        )

    # ── Pitcher's season leaderboard position ─────────────────────────────────
    avg = lb.get_pitcher_average(data.pitcher_id)
    games = lb.get_pitcher_games(data.pitcher_id)
    rank = lb.pitcher_rank(data.pitcher_id)
    if avg is not None:
        rank_str = f"#{rank}" if rank else "—"
        embed.add_field(
            name="📈 Season PAR",
            value=(
                f"Avg: **{avg:.1f}**  ·  Games: **{games}**  ·  "
                f"Server Rank: **{rank_str}**"
            ),
            inline=False,
        )

    return embed


def build_leaderboard_embed(lb: Leaderboard, page: str = "averages") -> discord.Embed:
    """Build a leaderboard embed. page = 'averages' | 'individual'"""

    if page == "averages":
        embed = discord.Embed(
            title="🏆  Phillies Therapy PAR Leaderboard — Season Averages",
            color=PHILLIES_RED,
            timestamp=datetime.utcnow(),
        )
        top = lb.top_averages(n=10, min_games=1)
        if not top:
            embed.description = "_No games recorded yet._"
        else:
            medals = ["🥇", "🥈", "🥉"] + ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            lines = []
            for i, entry in enumerate(top):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                bar = _par_bar(entry["avg"], 8)
                lines.append(
                    f"{medal} **{entry['name']}**  {bar}  "
                    f"`{entry['avg']:.1f}` avg  ·  {entry['games']}G  ·  best {entry['best']}"
                )
            embed.description = "\n".join(lines)

    else:  # individual
        embed = discord.Embed(
            title="⭐  Phillies Therapy PAR Leaderboard — Top Performances",
            color=PHILLIES_RED,
            timestamp=datetime.utcnow(),
        )
        top = lb.top_individual(n=10)
        if not top:
            embed.description = "_No games recorded yet._"
        else:
            medals = ["🥇", "🥈", "🥉"] + ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            lines = []
            for i, rec in enumerate(top):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                lines.append(
                    f"{medal} **{rec.pitcher_name}** vs {rec.opponent}  `{rec.game_date}`  ·  "
                    f"**{rec.score:.1f}** PAR  ·  {rec.ip} IP  {rec.k}K/{rec.bb}BB  {rec.er}ER"
                )
            embed.description = "\n".join(lines)

    embed.set_footer(text="Philly Ace Rating (PAR) · Phillies Therapy Bot")
    return embed


def _format_raw(name: str, val: float) -> str:
    if name in ("strike_ball_ratio", "csw"):
        return f"{val:.1f}%"
    if name == "batted_ball_quality":
        return f"{val:.1f} mph" if val else "N/A"
    if name == "efficiency":
        return f"{val:.1f} IP"
    return str(int(val))
