"""
Embed builders for the live stat props system.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import discord

from .stats import RATE_STATS, STAT_DEFINITIONS, parse_ip

# Status → display
_EMOJI = {
    "over":    "✅",
    "under":   "⏳",
    "push":    "➡️",
    "no_data": "⚫",
}
_LABEL = {
    "over":    "**OVER**",
    "under":   "under",
    "push":    "PUSH",
    "no_data": "—",
}


def fmt_val(val: Optional[float], stat: str) -> str:
    """Format a stat value for display."""
    if val is None:
        return "—"
    if stat == "innings_pitched":
        full = int(val)
        outs = round((val - full) * 3)
        return f"{full}.{outs}"
    if stat in RATE_STATS:
        # Baseball convention: .300 below 1.000, 1.050 at or above 1.000
        formatted = f"{val:.3f}"
        return formatted.lstrip("0") if val < 1.0 else formatted
    if val == int(val):
        return str(int(val))
    return f"{val:.1f}"


def make_alert_embed(
    prop: dict,
    current_value: float,
    game_info: Optional[dict],
) -> discord.Embed:
    """Build an embed announcing that a player has gone OVER their line."""
    stat_display = STAT_DEFINITIONS[prop["stat"]]["display"]
    player = prop["player_name"]
    line = prop["line"]
    scope = prop["scope"]

    embed = discord.Embed(
        title="🎯 PROP ALERT — OVER HIT!",
        color=discord.Color.green(),
    )
    embed.add_field(
        name=f"{player} — {stat_display}",
        value=f"Line: **{fmt_val(line, prop['stat'])}** | Current: **{fmt_val(current_value, prop['stat'])}**",
        inline=False,
    )

    if scope == "game" and game_info:
        away = game_info.get("away", "?")
        home = game_info.get("home", "?")
        inning = game_info.get("inning", "?")
        half = game_info.get("inning_half", "")
        half_label = "Top" if "top" in half.lower() else ("Bot" if half else "")
        embed.set_footer(text=f"{away} @ {home}  •  {half_label} {inning}".strip())
    elif scope == "season":
        embed.set_footer(text=f"Season total  •  {datetime.now().year}")

    return embed


def make_scoreboard_embed(prop_values: list[dict]) -> discord.Embed:
    """
    Build the live scoreboard embed.

    prop_values is a list of dicts:
        { "prop": dict, "current_value": float|None, "status": str, "game_pk": int|None }
    """
    embed = discord.Embed(
        title=f"📊 Props Scoreboard  —  {datetime.now().strftime('%B %-d, %Y')}",
        color=discord.Color.blue(),
    )

    game_props   = [pv for pv in prop_values if pv["prop"]["scope"] == "game"]
    season_props = [pv for pv in prop_values if pv["prop"]["scope"] == "season"]

    def _row(pv: dict) -> str:
        prop = pv["prop"]
        stat = prop["stat"]
        stat_display = STAT_DEFINITIONS[stat]["display"]
        emoji = _EMOJI[pv["status"]]
        label = _LABEL[pv["status"]]
        val_str  = fmt_val(pv["current_value"], stat)
        line_str = fmt_val(prop["line"], stat)
        return (
            f"{emoji} **{prop['player_name']}** — {stat_display} "
            f"O/U {line_str} | {val_str} — {label}"
        )

    if game_props:
        embed.add_field(
            name="🎮 Game Props",
            value="\n".join(_row(pv) for pv in game_props),
            inline=False,
        )

    if season_props:
        embed.add_field(
            name="📅 Season Props",
            value="\n".join(_row(pv) for pv in season_props),
            inline=False,
        )

    if not game_props and not season_props:
        embed.description = "No props configured yet. Use `/prop add` to get started."

    embed.set_footer(text=f"Updated {datetime.now().strftime('%-I:%M %p')}")
    return embed
