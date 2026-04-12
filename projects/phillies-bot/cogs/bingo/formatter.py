"""
Embed builders for the Bingo game.

  make_join_confirm_embed  — ephemeral board preview shown on /bingo join
  make_win_announcement_embed — public post to bingo channel on a win
  make_pre_game_reminder_embed — public post ~1 hour before first pitch
  make_leaderboard_embed   — public top-5 season scores

All functions accept an optional `variant_label` (e.g. "Phillies", "League")
that is used in embed titles and footers to distinguish game variants.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    variant_label: str = "Phillies",
) -> discord.Embed:
    """
    Ephemeral embed sent back to a player after /bingo join.
    Shows today's win type and a preview list of the day's events.
    """
    win_label = WIN_TYPE_LABELS.get(win_type, win_type)

    embed = discord.Embed(
        title=f"🎱 You're in — {variant_label} Bingo!",
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
        player_part = sq["player_name"] if sq["player_name"] != "Any" else "Any player"
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
# Pre-game reminder
# ---------------------------------------------------------------------------

def make_pre_game_reminder_embed(
    variant_label: str,
    game_start: datetime,
    games: list[dict],
) -> discord.Embed:
    """
    Public embed posted to the bingo channel ~1 hour before the first pitch.
    Prompts users to join with /bingo join before the game starts.

    game_start: UTC datetime of the earliest upcoming game.
    games:      full list of today's games (used to show matchup info).
    """
    now = datetime.now(timezone.utc)
    minutes_until = int((game_start - now).total_seconds() / 60)

    if minutes_until >= 60:
        time_str = f"~{minutes_until // 60}h {minutes_until % 60}m"
    else:
        time_str = f"~{minutes_until}m"

    # Build matchup line(s) from the games list
    matchup_lines: list[str] = []
    for g in games:
        away = g.get("away_name", "Away")
        home = g.get("home_name", "Home")
        matchup_lines.append(f"**{away}** @ **{home}**")
    matchup_text = "\n".join(matchup_lines) if matchup_lines else ""

    embed = discord.Embed(
        title=f"⚾ First pitch in {time_str} — join {variant_label} Bingo!",
        description=(
            f"{matchup_text}\n\n" if matchup_text else ""
        ) + "Use `/bingo join` to get your board before the game starts!",
        colour=discord.Colour.red(),
    )
    embed.set_footer(text=f"{variant_label} Bingo · boards lock in once the first play is recorded")
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
    variant_label: str = "Phillies",
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
    embed.set_footer(text=f"{variant_label} Bingo · {game_date}")
    return embed


# ---------------------------------------------------------------------------
# Season leaderboard
# ---------------------------------------------------------------------------

def make_key_embed() -> discord.Embed:
    """
    Ephemeral reference card explaining the board's symbols and abbreviations.
    """
    embed = discord.Embed(
        title="📖 Bingo Board Key",
        colour=discord.Colour.blurple(),
    )

    embed.add_field(
        name="Symbols",
        value="✅  Square marked\n⬜  Not yet marked\n⭐  FREE (always marked)",
        inline=False,
    )

    embed.add_field(
        name="Label Format",
        value=(
            "`~HR`  = **any** player hit a HR\n"
            "`TuHR` = **Turner** hit a HR\n"
            "*(first 2 letters of last name + event code)*"
        ),
        inline=False,
    )

    batting = (
        "`HR` Home Run\n"
        "`2B` Double\n"
        "`3B` Triple\n"
        "`SB` Stolen Base\n"
        "`CS` Caught Stealing\n"
        "`HP` Hit by Pitch\n"
        "`BB` Walk\n"
        "`IB` Intentional Walk\n"
        "`KS` Strikeout (swing)\n"
        "`KL` Strikeout (look)\n"
        "`Bn` Sac Bunt\n"
        "`SF` Sac Fly\n"
        "`FC` Fielder's Choice\n"
        "`GS` Grand Slam"
    )
    game = (
        "`K`  Pitcher strikeout\n"
        "`BK` Balk\n"
        "`WP` Wild Pitch\n"
        "`PO` Pickoff\n"
        "`PB` Passed Ball\n"
        "`E`  Error\n"
        "`DP` Double Play\n"
        "`TP` Triple Play\n"
        "`CI` Catcher's Interference\n"
        "`LC` Lead Change\n"
        "`XI` Extra Innings\n"
        "`CB` Comeback Win"
    )

    embed.add_field(name="Batting / Fielding", value=batting, inline=True)
    embed.add_field(name="Pitching / Game", value=game, inline=True)

    return embed


def make_leaderboard_embed(
    entries: list[dict],
    guild: Optional[discord.Guild],
    season: int,
    variant_label: str = "Phillies",
) -> discord.Embed:
    """
    Public embed showing top 5 season bingo scores.

    entries: list of dicts with {user_id, total_points, wins, games_played}
    guild:   used to resolve current server nicknames; may be None
    """
    embed = discord.Embed(
        title=f"🏆 {variant_label} Bingo — {season} Season Leaderboard",
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
