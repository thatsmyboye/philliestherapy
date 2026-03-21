"""
Discord embed builder for SP performance reports.
"""

import discord
from datetime import datetime
from .scoring import PARResult, ComponentScore
from .leaderboard import Leaderboard, GameRecord

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


def _par_bar_plain(score: float, length: int = 8) -> str:
    """Return a plain-text progress bar (no backticks) for use inside code blocks."""
    filled = round(score / 100 * length)
    return "█" * filled + "░" * (length - filled)


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
    opponent_str = f"{data.opponent} (ST)" if data.is_spring_training else data.opponent
    title = (
        f"{result.grade_emoji}  {result.pitcher_name}  |  "
        f"PHI {home_away_str} {opponent_str}  ·  {data.game_date}"
    )

    embed = discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Pitcher Ace Rating (PAR) · Phillies Therapy Bot")

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
    embed.add_field(
        name="🏟️ Pitcher Ace Rating (PAR)",
        value=f"{result.total_score:.1f} / 100\n{bar}",
        inline=True,
    )
    embed.add_field(
        name="📋 Grade",
        value=f"**{result.grade_emoji}  {result.grade_letter}**",
        inline=True,
    )

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
            NAME_W = 21
            header = f"{'#':>3}  {'Name':<{NAME_W}}  {'Bar':<8}  {'Avg':>5}  {'G':>2}  {'Best':>5}"
            sep = "─" * len(header)
            rows = [header, sep]
            for i, entry in enumerate(top):
                name = entry["name"][:NAME_W]
                bar = _par_bar_plain(entry["avg"], 8)
                rows.append(
                    f"{i+1:>3}  {name:<{NAME_W}}  {bar}  "
                    f"{entry['avg']:>5.1f}  {entry['games']:>2}G  {entry['best']:>5.1f}"
                )
            embed.description = "```\n" + "\n".join(rows) + "\n```"

    elif page == "individual":
        embed = discord.Embed(
            title="⭐  Phillies Therapy PAR Leaderboard — Top Performances",
            color=PHILLIES_RED,
            timestamp=datetime.utcnow(),
        )
        top = lb.top_individual(n=10)
        if not top:
            embed.description = "_No games recorded yet._"
        else:
            NAME_W = 18
            header = f"{'#':>3}  {'Name':<{NAME_W}}  {'Date':<10}  {'PAR':>5}  {'IP':>4}  {'K':>3}  {'BB':>3}  {'ER':>3}"
            sep = "─" * len(header)
            rows = [header, sep]
            for i, rec in enumerate(top):
                name = rec.pitcher_name[:NAME_W]
                rows.append(
                    f"{i+1:>3}  {name:<{NAME_W}}  {rec.game_date:<10}  "
                    f"{rec.score:>5.1f}  {rec.ip:>4}  {rec.k:>3}  {rec.bb:>3}  {rec.er:>3}"
                )
            embed.description = "```\n" + "\n".join(rows) + "\n```"

    else:  # cal — chronological recent-games view
        embed = discord.Embed(
            title="📅  Phillies Therapy PAR Leaderboard — Recent Games",
            color=PHILLIES_RED,
            timestamp=datetime.utcnow(),
        )
        recent = sorted(lb._records, key=lambda r: r.game_date, reverse=True)[:10]
        if not recent:
            embed.description = "_No games recorded yet._"
        else:
            NAME_W = 18
            header = f"{'Date':<10}  {'Name':<{NAME_W}}  {'vs':>3}  {'PAR':>5}  {'Grd':<4}  {'IP':>4}  {'K':>3}  {'BB':>3}  {'ER':>3}"
            sep = "─" * len(header)
            rows = [header, sep]
            for rec in recent:
                name = rec.pitcher_name[:NAME_W]
                rows.append(
                    f"{rec.game_date:<10}  {name:<{NAME_W}}  {rec.opponent:>3}  "
                    f"{rec.score:>5.1f}  {rec.grade:<4}  {rec.ip:>4}  {rec.k:>3}  {rec.bb:>3}  {rec.er:>3}"
                )
            embed.description = "```\n" + "\n".join(rows) + "\n```"

    embed.set_footer(text="Pitcher Ace Rating (PAR) · Phillies Therapy Bot")
    return embed


def _format_raw(name: str, val: float) -> str:
    if name in ("strike_ball_ratio", "csw"):
        return f"{val:.1f}%"
    if name == "batted_ball_quality":
        return f"{val:.1f} mph" if val else "N/A"
    if name == "efficiency":
        return f"{val:.1f} IP"
    return str(int(val))
