"""
Embed builders for the Phillies Bingo game.

  make_join_confirm_embed  — ephemeral board preview shown on /bingo join
  make_win_announcement_embed — public post to bingo channel on a win
  make_leaderboard_embed   — public top-5 season scores
"""
from __future__ import annotations

from typing import Optional

import discord

from .events import WIN_TYPE_LABELS, EVENT_BASE_LABEL

_PLACE_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
_PLACE_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def _place_str(place: int) -> str:
    suffix = _PLACE_SUFFIXES.get(place, "th")
    return f"{place}{suffix}"


# ---------------------------------------------------------------------------
# Join confirmation
# ---------------------------------------------------------------------------

def make_join_confirm_embed(
    win_type: str,
    event_pool: list[dict],
    game_date: str,
) -> discord.Embed:
    """
    Ephemeral embed sent back to a player after /bingo join.
    Shows today's win type and a preview list of the day's events.
    """
    win_label = WIN_TYPE_LABELS.get(win_type, win_type)

    embed = discord.Embed(
        title="🎱 You're in — Phillies Bingo!",
        description=(
            f"Your personal 5×5 board has been generated for **{game_date}**.\n"
            "Squares will be marked automatically as events occur in today's game.\n\n"
            f"**Today's win condition:** {win_label}\n\n"
            "Use `/bingo check` anytime to see your current board."
        ),
        colour=discord.Colour.red(),
    )

    # Summarise today's event types
    event_lines: list[str] = []
    for sq in event_pool:
        player_part = sq["player_name"] if sq["player_name"] != "Any" else "Any Phillies player"
        base = EVENT_BASE_LABEL.get(sq["event_id"], sq["event_id"])
        event_lines.append(f"• **{player_part}** — {base}")

    # Split into two columns for readability
    half = len(event_lines) // 2
    col1 = "\n".join(event_lines[:half]) or "—"
    col2 = "\n".join(event_lines[half:]) or "—"

    embed.add_field(name="Today's Squares (1/2)", value=col1, inline=True)
    embed.add_field(name="Today's Squares (2/2)", value=col2, inline=True)

    embed.set_footer(text="Good luck! 🍀  Points awarded to the first 10 players to get Bingo.")
    return embed


# ---------------------------------------------------------------------------
# Win announcement
# ---------------------------------------------------------------------------

def make_win_announcement_embed(
    display_name: str,
    place: int,
    points: int,
    win_type: str,
    game_date: str,
) -> discord.Embed:
    """
    Public embed posted to the bingo channel when a player achieves bingo.
    """
    medal = _PLACE_MEDALS.get(place, "🎉")
    win_label = WIN_TYPE_LABELS.get(win_type, win_type)
    place_label = _place_str(place)

    embed = discord.Embed(
        title=f"{medal} BINGO! {display_name} wins {place_label} place!",
        description=(
            f"**{display_name}** completed a **{win_label}** bingo!\n"
            f"**+{points} point{'s' if points != 1 else ''}** added to their season total."
        ),
        colour=discord.Colour.gold() if place == 1 else discord.Colour.green(),
    )
    embed.set_footer(text=f"Phillies Bingo · {game_date}")
    return embed


# ---------------------------------------------------------------------------
# Season leaderboard
# ---------------------------------------------------------------------------

def make_leaderboard_embed(
    entries: list[dict],
    guild: Optional[discord.Guild],
    season: int,
) -> discord.Embed:
    """
    Public embed showing top 5 season bingo scores.

    entries: list of dicts with {user_id, total_points, wins, games_played}
    guild:   used to resolve current server nicknames; may be None
    """
    embed = discord.Embed(
        title=f"🏆 Phillies Bingo — {season} Season Leaderboard",
        colour=discord.Colour.red(),
    )

    if not entries:
        embed.description = "No scores recorded yet this season."
        return embed

    lines: list[str] = []
    for i, entry in enumerate(entries):
        place = i + 1
        medal = _PLACE_MEDALS.get(place, f"**{place}.**")
        uid = int(entry["user_id"])

        # Resolve display name from guild member
        display_name = f"<@{uid}>"
        if guild:
            member = guild.get_member(uid)
            if member:
                display_name = member.display_name

        pts = entry["total_points"]
        wins = entry.get("wins", 0)
        gp = entry.get("games_played", 0)
        lines.append(
            f"{medal} **{display_name}** — {pts} pt{'s' if pts != 1 else ''} "
            f"({wins} win{'s' if wins != 1 else ''} · {gp} game{'s' if gp != 1 else ''})"
        )

    embed.description = "\n".join(lines)
    embed.set_footer(text="Use /bingo join to play on the next game day!")
    return embed
