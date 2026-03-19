"""
Cog: Stolen base / caught stealing live alerts.

Polls live Phillies game data every 30 seconds and posts an alert whenever
any player attempts a steal (success or failure) in a Phillies game.

Each alert includes:
  - Outcome (SB or CS) and base
  - Difficulty star rating (0.5–5.0) computed from:
      * Pitch type and speed on the steal pitch
      * Catcher's season-average pop time (Baseball Savant)
      * Runner's season-average sprint speed (Baseball Savant)
  - Lead distance if available from Baseball Savant

Slash command:
  /steal-grades  — season leaderboard of runners ranked by weighted success rate
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import utils.state as state_store
from utils.mlb_data import (
    CURRENT_SEASON,
    PITCH_TYPE_LABELS,
    get_live_game_data,
    get_pop_time_leaderboard,
    get_sprint_speed_leaderboard,
    get_todays_phillies_games,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STEAL_EVENT_TYPES = {
    "stolen_base_2b",
    "stolen_base_3b",
    "stolen_base_home",
    "caught_stealing_2b",
    "caught_stealing_3b",
    "caught_stealing_home",
}

SUCCESS_EVENT_TYPES = {
    "stolen_base_2b",
    "stolen_base_3b",
    "stolen_base_home",
}

BASE_LABEL: dict[str, str] = {
    "stolen_base_2b": "2nd base",
    "stolen_base_3b": "3rd base",
    "stolen_base_home": "home",
    "caught_stealing_2b": "2nd base",
    "caught_stealing_3b": "3rd base",
    "caught_stealing_home": "home",
}

# Pitch families that give the catcher the cleanest receive
FASTBALL_TYPES = {"FF", "SI", "FT", "FA", "FC"}

# Minimum attempts to appear in /steal-grades leaderboard
MIN_ATTEMPTS_FOR_LEADERBOARD = 2

PHILLIES_RED = 0xE81828


# ---------------------------------------------------------------------------
# Difficulty scoring
# ---------------------------------------------------------------------------

def _compute_difficulty(
    pitch_speed: Optional[float],
    pitch_type: Optional[str],
    pop_time: Optional[float],
    sprint_speed: Optional[float],
    lead_distance: Optional[float] = None,
) -> float:
    """
    Return steal difficulty on a 0.5–5.0 scale (higher = harder to steal).

    Components:
      Pitch speed    — faster pitch → less time for runner → harder (0–2.0 pts)
      Pitch type     — fastball family → cleaner receive → +0.25 pts
      Catcher pop    — lower pop time → harder (0–1.5 pts)
      Runner speed   — faster runner → easier (−0–1.0 pts)
      Lead distance  — longer lead → easier (−0–0.5 pts, optional)

    When a component's data is unavailable, a neutral league-average value
    is substituted so the rating still reflects the available data.
    """
    score = 1.0

    # --- Pitch speed (80 mph = +0, 100 mph = +2.0) ---
    if pitch_speed is not None:
        spd_factor = max(0.0, min(1.0, (pitch_speed - 80.0) / 20.0))
        score += spd_factor * 2.0
    else:
        score += 0.8  # ~92 mph league-average substitute

    # --- Pitch type bonus ---
    if pitch_type in FASTBALL_TYPES:
        score += 0.25

    # --- Catcher pop time (1.85s = +1.5, 2.20s = +0) ---
    if pop_time is not None:
        pop_factor = max(0.0, min(1.0, (2.20 - pop_time) / 0.35))
        score += pop_factor * 1.5
    else:
        score += 0.75  # ~2.0s league-average substitute

    # --- Runner sprint speed (24 ft/s = no reduction, 31 ft/s = −1.0) ---
    if sprint_speed is not None:
        sprint_factor = max(0.0, min(1.0, (sprint_speed - 24.0) / 7.0))
        score -= sprint_factor * 1.0
    # No sprint data → no adjustment (stays at current score)

    # --- Lead distance (8 ft = no reduction, 16 ft = −0.5) ---
    if lead_distance is not None:
        lead_factor = max(0.0, min(1.0, (lead_distance - 8.0) / 8.0))
        score -= lead_factor * 0.5

    # Clamp to valid range and round to nearest 0.5
    score = max(0.5, min(5.0, score))
    return round(score * 2) / 2


def _format_stars(rating: float) -> str:
    """
    Convert a 0.5–5.0 rating to a visual star string.
    e.g. 3.5 → "★★★½☆  (3.5/5)"
    """
    rating = max(0.5, min(5.0, rating))
    full = int(rating)
    half = 1 if (rating - full) >= 0.25 else 0
    empty = 5 - full - half
    return "★" * full + ("½" if half else "") + "☆" * empty + f"  ({rating}/5)"


# ---------------------------------------------------------------------------
# Game data helpers
# ---------------------------------------------------------------------------

def _build_player_name_map(data: dict) -> dict[int, str]:
    """Extract player_id → fullName from the boxscore of a live game."""
    name_map: dict[int, str] = {}
    try:
        teams = data["liveData"]["boxscore"]["teams"]
        for side in ("home", "away"):
            for key, player in teams[side]["players"].items():
                pid = player.get("person", {}).get("id")
                fname = player.get("person", {}).get("fullName", "")
                if pid and fname:
                    name_map[pid] = fname
    except (KeyError, TypeError):
        pass
    return name_map


def _get_catcher(data: dict, half_inning: str) -> tuple[Optional[int], str]:
    """
    Return (catcher_id, catcher_name) for the fielding team on this half-inning.
    half_inning: "top" → home team fields; "bottom" → away team fields.
    """
    fielding_side = "home" if half_inning == "top" else "away"
    try:
        players = data["liveData"]["boxscore"]["teams"][fielding_side]["players"]
        for key, player in players.items():
            pos = player.get("position", {}).get("abbreviation", "")
            if pos == "C":
                pid = player["person"]["id"]
                name = player["person"].get("fullName", "Unknown")
                return pid, name
    except (KeyError, TypeError):
        pass
    return None, "Unknown"


def _find_pitch_before_event(play_events: list[dict], event_idx: int) -> Optional[dict]:
    """Return the last pitch playEvent that precedes the steal action at event_idx."""
    for i in range(event_idx - 1, -1, -1):
        if play_events[i].get("isPitch"):
            return play_events[i]
    return None


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class StealMonitorCog(commands.Cog, name="StealMonitor"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._state: dict = state_store.load()
        self._alerts_channel_id: int = int(os.environ.get("ALERTS_CHANNEL_ID", 0))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.monitor_steals.is_running():
            self.monitor_steals.start()

    # ------------------------------------------------------------------
    # Main monitoring loop
    # ------------------------------------------------------------------

    @tasks.loop(seconds=30)
    async def monitor_steals(self) -> None:
        loop = asyncio.get_event_loop()
        games = await loop.run_in_executor(None, get_todays_phillies_games)
        live_games = [g for g in games if g.get("status") == "In Progress"]

        changed = False
        for game in live_games:
            try:
                updated = await self._check_game(game["game_id"])
                changed = changed or updated
            except Exception as exc:
                print(f"[steal_monitor] Error checking game {game['game_id']}: {exc}")

        if changed:
            state_store.save(self._state)

    @monitor_steals.before_loop
    async def before_monitor(self) -> None:
        await self.bot.wait_until_ready()

    @monitor_steals.error
    async def monitor_error(self, error: Exception) -> None:
        print(f"[steal_monitor] Loop error: {error}")

    # ------------------------------------------------------------------
    # Per-game processing
    # ------------------------------------------------------------------

    async def _check_game(self, game_pk: int) -> bool:
        """
        Scan all plays in the game for unprocessed steal events.
        Returns True if any new steal was detected.
        """
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, get_live_game_data, game_pk)
        if not data:
            return False

        all_plays: list[dict] = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
        if not all_plays:
            return False

        # Player name lookup built once per game poll
        name_map = _build_player_name_map(data)

        # Per-game event tracking: steal_event_counts[game_pk][play_idx] = events_processed
        game_pk_str = str(game_pk)
        event_counts: dict = self._state.setdefault("steal_event_counts", {}).setdefault(game_pk_str, {})

        channel = self.bot.get_channel(self._alerts_channel_id)
        found_new = False

        loop2 = asyncio.get_event_loop()
        # Pre-fetch leaderboards once per game poll (cached anyway)
        sprint_map, pop_map = await asyncio.gather(
            loop2.run_in_executor(None, get_sprint_speed_leaderboard),
            loop2.run_in_executor(None, get_pop_time_leaderboard),
        )

        for play_idx, play in enumerate(all_plays):
            play_events: list[dict] = play.get("playEvents", [])
            play_idx_str = str(play_idx)
            last_processed = event_counts.get(play_idx_str, 0)

            if len(play_events) <= last_processed:
                continue

            # Update event count for this play
            event_counts[play_idx_str] = len(play_events)

            # Only check the NEW events since last poll
            for event_idx in range(last_processed, len(play_events)):
                event = play_events[event_idx]
                if not event.get("isBaseRunningPlay"):
                    continue

                event_type = event.get("details", {}).get("eventType", "")
                if event_type not in STEAL_EVENT_TYPES:
                    continue

                fingerprint = f"{game_pk}:{play_idx}:{event_idx}"
                if state_store.has_steal_event_posted(self._state, fingerprint):
                    continue

                await self._process_steal(
                    event=event,
                    event_type=event_type,
                    play=play,
                    play_events=play_events,
                    event_idx=event_idx,
                    game_pk=game_pk,
                    data=data,
                    name_map=name_map,
                    sprint_map=sprint_map,
                    pop_map=pop_map,
                    channel=channel,
                    fingerprint=fingerprint,
                )
                state_store.record_steal_event_posted(self._state, fingerprint)
                found_new = True

        return found_new

    async def _process_steal(
        self,
        event: dict,
        event_type: str,
        play: dict,
        play_events: list[dict],
        event_idx: int,
        game_pk: int,
        data: dict,
        name_map: dict[int, str],
        sprint_map: dict,
        pop_map: dict,
        channel: Optional[discord.TextChannel],
        fingerprint: str,
    ) -> None:
        success = event_type in SUCCESS_EVENT_TYPES
        base = BASE_LABEL.get(event_type, "unknown base")

        # --- Runner ---
        runner_id: Optional[int] = event.get("player", {}).get("id")
        runner_name = name_map.get(runner_id, "Unknown") if runner_id else "Unknown"

        # --- Pitcher (from play matchup) ---
        pitcher_id: Optional[int] = play.get("matchup", {}).get("pitcher", {}).get("id")
        pitcher_name = name_map.get(pitcher_id, play.get("matchup", {}).get("pitcher", {}).get("fullName", "Unknown"))

        # --- Catcher ---
        half_inning = play.get("about", {}).get("halfInning", "top")
        catcher_id, catcher_name = _get_catcher(data, half_inning)

        # --- Pitch on the steal attempt ---
        pitch_event = _find_pitch_before_event(play_events, event_idx)
        pitch_speed: Optional[float] = None
        pitch_type: Optional[str] = None
        pitch_type_label: Optional[str] = None

        if pitch_event:
            pitch_speed = pitch_event.get("pitchData", {}).get("startSpeed")
            if pitch_speed is not None:
                pitch_speed = float(pitch_speed)
            pitch_type = pitch_event.get("details", {}).get("type", {}).get("code")
            pitch_type_label = PITCH_TYPE_LABELS.get(pitch_type, pitch_type) if pitch_type else None

        # --- Statcast season averages ---
        runner_stats = sprint_map.get(runner_id, {}) if runner_id else {}
        sprint_speed: Optional[float] = runner_stats.get("sprint_speed")
        lead_distance: Optional[float] = runner_stats.get("lead_distance")

        catcher_stats = pop_map.get(catcher_id, {}) if catcher_id else {}
        pop_time: Optional[float] = catcher_stats.get("pop_time")

        # --- Difficulty ---
        difficulty = _compute_difficulty(pitch_speed, pitch_type, pop_time, sprint_speed, lead_distance)

        # --- Persist attempt ---
        today = date.today().isoformat()
        attempt = {
            "game_pk": game_pk,
            "date": today,
            "success": success,
            "difficulty": difficulty,
            "base": base,
            "pitcher_name": pitcher_name,
            "catcher_name": catcher_name,
            "pitch_type": pitch_type,
            "pitch_speed": pitch_speed,
            "pop_time": pop_time,
            "sprint_speed": sprint_speed,
        }
        if runner_id:
            state_store.add_steal_attempt(self._state, runner_id, runner_name, attempt)

        # --- Post embed ---
        if channel:
            embed = _steal_embed(
                success=success,
                base=base,
                runner_name=runner_name,
                pitcher_name=pitcher_name,
                catcher_name=catcher_name,
                pitch_type_label=pitch_type_label,
                pitch_speed=pitch_speed,
                pop_time=pop_time,
                sprint_speed=sprint_speed,
                lead_distance=lead_distance,
                difficulty=difficulty,
            )
            try:
                await channel.send(embed=embed)
            except Exception as exc:
                print(f"[steal_monitor] Failed to send embed: {exc}")

    # ------------------------------------------------------------------
    # Slash command: /steal-grades
    # ------------------------------------------------------------------

    @app_commands.command(
        name="steal-grades",
        description="Season leaderboard of base stealers ranked by difficulty-weighted success rate",
    )
    async def steal_grades(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        grades = state_store.get_steal_grades(self._state)

        rows = []
        for pid_str, entry in grades.items():
            attempts = entry.get("attempts", [])
            if len(attempts) < MIN_ATTEMPTS_FOR_LEADERBOARD:
                continue

            sb = sum(1 for a in attempts if a["success"])
            cs = sum(1 for a in attempts if not a["success"])
            total_weight = sum(a["difficulty"] for a in attempts)
            weighted_success = sum(a["difficulty"] for a in attempts if a["success"])
            wsr = (weighted_success / total_weight * 100) if total_weight > 0 else 0.0
            avg_diff = total_weight / len(attempts)

            rows.append({
                "name": entry["name"],
                "sb": sb,
                "cs": cs,
                "wsr": wsr,
                "avg_diff": avg_diff,
                "attempts": len(attempts),
            })

        if not rows:
            await interaction.followup.send(
                embed=discord.Embed(
                    title=":no_entry_sign: No steal data yet",
                    description=f"No runners have {MIN_ATTEMPTS_FOR_LEADERBOARD}+ steal attempts recorded in Phillies games this season.",
                    color=PHILLIES_RED,
                ).set_footer(text="Phillies Bot • Steal Grades")
            )
            return

        rows.sort(key=lambda r: r["wsr"], reverse=True)

        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, r in enumerate(rows[:15], start=1):
            medal = medals.get(i, f"`{i:>2}.`")
            stars = _format_stars(round(r["avg_diff"] * 2) / 2)
            lines.append(
                f"{medal} **{r['name']}** — "
                f"{r['sb']} SB / {r['cs']} CS  |  "
                f"**{r['wsr']:.1f}%** wt. success  |  "
                f"avg diff {stars}"
            )

        description = "\n".join(lines)
        description += (
            f"\n\n-# Weighted success rate = sum(difficulty × success) / sum(difficulty)\n"
            f"-# Min {MIN_ATTEMPTS_FOR_LEADERBOARD} attempts to qualify  •  {CURRENT_SEASON} season"
        )

        embed = discord.Embed(
            title=f":runner: Steal Grades — {CURRENT_SEASON}",
            description=description,
            color=PHILLIES_RED,
        ).set_footer(text="Phillies Bot • Steal Grades  •  Difficulty: pitch speed + type, catcher pop time, runner sprint speed")

        await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# Embed builder
# ---------------------------------------------------------------------------

def _steal_embed(
    success: bool,
    base: str,
    runner_name: str,
    pitcher_name: str,
    catcher_name: str,
    pitch_type_label: Optional[str],
    pitch_speed: Optional[float],
    pop_time: Optional[float],
    sprint_speed: Optional[float],
    lead_distance: Optional[float],
    difficulty: float,
) -> discord.Embed:
    if success:
        title = f":runner: Stolen Base — {runner_name}"
        outcome_line = f"Steals **{base}**"
        color = PHILLIES_RED
    else:
        title = f":no_entry_sign: Caught Stealing — {runner_name}"
        outcome_line = f"Thrown out at **{base}**"
        color = 0x808080

    stars_str = _format_stars(difficulty)

    # Pitch detail
    pitch_parts = []
    if pitch_type_label:
        pitch_parts.append(pitch_type_label)
    if pitch_speed is not None:
        pitch_parts.append(f"{pitch_speed:.1f} mph")
    pitch_detail = "  ".join(pitch_parts) if pitch_parts else "N/A"

    # Catcher detail
    pop_detail = f"Pop time: **{pop_time:.2f}s**" if pop_time is not None else "Pop time: N/A"

    # Runner detail
    runner_parts = []
    if sprint_speed is not None:
        runner_parts.append(f"Sprint speed: **{sprint_speed:.1f} ft/s**")
    if lead_distance is not None:
        runner_parts.append(f"Lead: **{lead_distance:.1f} ft**")
    runner_detail = "  ·  ".join(runner_parts) if runner_parts else "Statcast: N/A"

    embed = discord.Embed(
        title=title,
        description=f"{outcome_line}\n\n**Difficulty:** {stars_str}",
        color=color,
    )
    embed.add_field(name=f"Pitcher — {pitcher_name}", value=pitch_detail, inline=False)
    embed.add_field(name=f"Catcher — {catcher_name}", value=pop_detail, inline=True)
    embed.add_field(name=f"Runner — {runner_name}", value=runner_detail, inline=True)
    embed.set_footer(text="Phillies Bot • Steal Alert  •  Use /steal-grades for season leaderboard")
    return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StealMonitorCog(bot))
