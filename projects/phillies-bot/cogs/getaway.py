"""
Cog: /getaway slash command.

Measures how well (or poorly) a pitcher escapes the consequences of a genuinely
terrible pitch — one that is grooved in a hittable location, below average in
movement, or down in velocity — yet somehow produces a good outcome.

Scoring model:
  Badness (0–100):
    60% — Location: how centered/hittable was the pitch in the zone?
    20% — Movement: how far below the pitcher's season average break?
    20% — Velocity: how far below the pitcher's season average speed?

  Escape run value:
    Primarily sourced from delta_run_exp (Statcast, offense perspective → negated).
    Fallback: description-based approximation + xwOBA delta for balls in play.

  Leverage context: base-out state run expectancy (RE24) weights each escape
  by how much the situation mattered.
"""
from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.trends import _safe_mean
from utils.mlb_data import (
    PITCH_TYPE_LABELS,
    _to_float,
    _to_int,
    get_pitcher_statcast,
    is_early_regular_season,
    is_spring_training,
)
from utils.player_lookup import resolve_player

PHILLIES_RED = 0xE81828

# ---------------------------------------------------------------------------
# RE24 run expectancy table (2010–2019 MLB averages)
# Key: (outs, runners_bitmask)  bit 0=1B occupied, bit 1=2B, bit 2=3B
# ---------------------------------------------------------------------------
_RE24: dict[tuple[int, int], float] = {
    (0, 0): 0.481,  (0, 1): 0.859,  (0, 2): 1.100,  (0, 3): 1.473,
    (0, 4): 1.350,  (0, 5): 1.798,  (0, 6): 2.050,  (0, 7): 2.417,
    (1, 0): 0.254,  (1, 1): 0.509,  (1, 2): 0.664,  (1, 3): 0.908,
    (1, 4): 0.897,  (1, 5): 1.140,  (1, 6): 1.352,  (1, 7): 1.520,
    (2, 0): 0.098,  (2, 1): 0.224,  (2, 2): 0.319,  (2, 3): 0.429,
    (2, 4): 0.387,  (2, 5): 0.537,  (2, 6): 0.544,  (2, 7): 0.783,
}
_RE24_BASELINE = 0.481  # (0 outs, empty bases) — leverage normalizer

# ---------------------------------------------------------------------------
# Fallback pitch-outcome escape values when delta_run_exp is unavailable.
# Sign convention (pitcher's perspective): positive = pitcher benefited.
# ---------------------------------------------------------------------------
_DESC_ESCAPE_RV: dict[str, float] = {
    "swinging_strike":          0.45,
    "swinging_strike_blocked":  0.45,
    "foul_tip":                 0.40,
    "called_strike":            0.30,
    "foul":                     0.05,
    "foul_bunt":                0.05,
    "ball":                    -0.05,
    "blocked_ball":            -0.04,
    "called_ball":             -0.05,
}

_LEAGUE_AVG_XWOBA = 0.320  # approximate MLB-average xwOBA on contact

_MIN_BADNESS   = 50.0  # score threshold to qualify as a "terrible" pitch
_MIN_TERRIBLE  = 15    # below this count the sample-size caveat fires
_MIN_PT_SAMPLE = 30    # minimum pitches of a type to establish baselines

# ---------------------------------------------------------------------------
# Pitch type choices (mirrors velocity.py pattern)
# ---------------------------------------------------------------------------
_PITCH_CHOICES = [
    app_commands.Choice(name=label, value=code)
    for code, label in PITCH_TYPE_LABELS.items()
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _run_expectancy(row: dict) -> float:
    """Return RE24 expected runs from the base-out state encoded in a Statcast row."""
    outs = max(0, min(2, _to_int(row.get("outs_when_up", 0))))
    runners = (
        (1 if str(row.get("on_1b", "")).strip() else 0)
        | (2 if str(row.get("on_2b", "")).strip() else 0)
        | (4 if str(row.get("on_3b", "")).strip() else 0)
    )
    return _RE24.get((outs, runners), _RE24_BASELINE)


def _leverage(row: dict) -> float:
    """RE24 state relative to empty/0-out baseline (1.0 = baseline leverage)."""
    return _run_expectancy(row) / _RE24_BASELINE


def _location_badness(
    plate_x: float, plate_z: float, sz_top: float, sz_bot: float
) -> float:
    """
    Return 0–1 score of how hittable the pitch location was.
    1.0 = dead center of the strike zone; 0.0 = well outside.
    """
    HALF_PLATE_W = 17.0 / 24.0  # half of 17-inch plate in feet (~0.708)
    zone_center_z = (sz_top + sz_bot) / 2.0
    zone_half_h = max((sz_top - sz_bot) / 2.0, 0.01)

    dx = plate_x / HALF_PLATE_W
    dz = (plate_z - zone_center_z) / zone_half_h
    dist = math.sqrt(dx ** 2 + dz ** 2)

    # dist=0 → center → badness 1.0; dist=1 → zone edge → ~0.25; dist>1.3 → ~0
    return max(0.0, min(1.0, 1.0 - 0.75 * dist))


def _movement_badness(pfx_x_in: float, pfx_z_in: float, avg_break_in: float) -> float:
    """
    Return 0–1 score of how flat/below-average the pitch movement was.
    0.5 = average; 1.0 = nearly zero break; 0.0 = well above average.
    """
    if avg_break_in <= 0:
        return 0.5
    total_break = math.sqrt(pfx_x_in ** 2 + pfx_z_in ** 2)
    ratio = total_break / avg_break_in
    # ratio 0.6 → badness 1.0; ratio 1.0 → 0.5; ratio ≥ 1.4 → 0.0
    return max(0.0, min(1.0, 1.0 - (ratio - 0.6) / 0.8))


def _velocity_badness(velo: float, avg_velo: float) -> float:
    """
    Return 0–1 score of how slow this pitch was vs. the pitcher's average.
    0.5 = at average; 1.0 = far below; 0.0 = at or above average.
    """
    if avg_velo <= 0:
        return 0.5
    diff = avg_velo - velo  # positive = below average
    # 3+ mph below avg → 1.0; at avg → 0.5; above avg → 0.0
    return max(0.0, min(1.0, 0.5 + diff / 6.0))


def _compute_pt_averages(rows: list[dict]) -> dict:
    """
    For each pitch type, compute the season baselines needed for badness scoring.
    Returns {pt: {n, avg_velo, avg_break_in, avg_pfx_x_in, avg_pfx_z_in}}.
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        pt = row.get("pitch_type", "").strip()
        if pt:
            by_type[pt].append(row)

    result: dict = {}
    for pt, pt_rows in by_type.items():
        n = len(pt_rows)
        velos = [
            v for v in (_to_float(r.get("release_speed")) for r in pt_rows)
            if v and v > 0
        ]
        pfx_xs = [
            v * 12
            for v in (_to_float(r.get("pfx_x")) for r in pt_rows)
            if v is not None
        ]
        pfx_zs = [
            v * 12
            for v in (_to_float(r.get("pfx_z")) for r in pt_rows)
            if v is not None
        ]
        avg_pfx_x = _safe_mean(pfx_xs) or 0.0
        avg_pfx_z = _safe_mean(pfx_zs) or 0.0

        result[pt] = {
            "n": n,
            "avg_velo": _safe_mean(velos) or 0.0,
            "avg_break_in": math.sqrt(avg_pfx_x ** 2 + avg_pfx_z ** 2),
            "avg_pfx_x_in": avg_pfx_x,
            "avg_pfx_z_in": avg_pfx_z,
        }
    return result


def _pitch_badness(row: dict, pt_averages: dict) -> Optional[float]:
    """
    Return composite badness 0–100 for a single pitch, or None if location
    data is missing.  Weights: 60% location · 20% movement · 20% velocity.
    """
    plate_x = _to_float(row.get("plate_x"))
    plate_z = _to_float(row.get("plate_z"))
    sz_top  = _to_float(row.get("sz_top"))
    sz_bot  = _to_float(row.get("sz_bot"))

    if any(v is None for v in (plate_x, plate_z, sz_top, sz_bot)):
        return None

    loc_bad = _location_badness(plate_x, plate_z, sz_top, sz_bot)  # type: ignore[arg-type]

    pt  = row.get("pitch_type", "").strip()
    avg = pt_averages.get(pt, {})
    has_baseline = avg.get("n", 0) >= _MIN_PT_SAMPLE

    # Movement component (inches, converted from feet CSV values)
    pfx_x = _to_float(row.get("pfx_x"))
    pfx_z = _to_float(row.get("pfx_z"))
    if has_baseline and pfx_x is not None and pfx_z is not None:
        mov_bad = _movement_badness(pfx_x * 12, pfx_z * 12, avg["avg_break_in"])
    else:
        mov_bad = 0.5  # neutral when no baseline

    # Velocity component
    velo = _to_float(row.get("release_speed"))
    if has_baseline and velo is not None and avg["avg_velo"] > 0:
        vel_bad = _velocity_badness(velo, avg["avg_velo"])
    else:
        vel_bad = 0.5

    return (0.60 * loc_bad + 0.20 * mov_bad + 0.20 * vel_bad) * 100


def _escape_run_value(row: dict) -> Optional[float]:
    """
    Return the run value "saved" by the pitcher on this pitch (pitcher's
    perspective: positive = pitcher benefited).

    Primary: delta_run_exp from Statcast (offense perspective, so negated).
    Fallback: description-based table + xwOBA delta for balls in play.
    """
    dre = _to_float(row.get("delta_run_exp"))
    if dre is not None:
        return -dre  # flip to pitcher's perspective

    desc = row.get("description", "").strip()
    if desc in _DESC_ESCAPE_RV:
        return _DESC_ESCAPE_RV[desc]

    if desc.startswith("hit_into_play"):
        xwoba = _to_float(row.get("estimated_woba_using_speedangle"))
        if xwoba is None:
            # Rough proxy from xBA when xwOBA absent
            xba = _to_float(row.get("estimated_ba_using_speedangle"))
            if xba is not None:
                xwoba = xba * 1.5
        if xwoba is not None:
            return _LEAGUE_AVG_XWOBA - xwoba  # positive = below-avg contact = pitcher wins

    return None


def _format_zone_desc(
    plate_x: float, plate_z: float, sz_top: float, sz_bot: float
) -> str:
    """Return a short human-readable location string, e.g. 'belt-high center'."""
    HALF_W = 17.0 / 24.0
    zone_center_z = (sz_top + sz_bot) / 2.0
    zone_half_h   = max((sz_top - sz_bot) / 2.0, 0.01)

    rel_x = plate_x / HALF_W
    if abs(rel_x) < 0.30:
        h_desc = "center"
    elif abs(rel_x) < 0.65:
        h_desc = "in" if rel_x > 0 else "away"
    elif abs(rel_x) < 1.0:
        h_desc = "inner third" if rel_x > 0 else "outer third"
    else:
        h_desc = "well inside" if rel_x > 0 else "well outside"

    rel_z = (plate_z - zone_center_z) / zone_half_h
    if abs(rel_z) < 0.30:
        v_desc = "belt-high"
    elif rel_z > 0.60:
        v_desc = "up"
    elif rel_z < -0.60:
        v_desc = "down"
    elif rel_z > 0:
        v_desc = "mid-high"
    else:
        v_desc = "mid-low"

    return f"{v_desc} {h_desc}"


def _grade(escape_rate: float) -> tuple[str, str]:
    """Map escape-rate percentage to (letter, label)."""
    if escape_rate >= 72:
        return "A+", "Elite Escape Artist"
    if escape_rate >= 65:
        return "A",  "Gets Away With Murder"
    if escape_rate >= 57:
        return "B",  "Above Average Escape"
    if escape_rate >= 48:
        return "C",  "League Average"
    if escape_rate >= 38:
        return "D",  "Pays the Price"
    return "F", "Meatballs for Everyone"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _analyze_getaway(rows: list[dict], pitch_type_filter: Optional[str] = None) -> dict:
    """
    Score every pitch in *rows* and return an analysis dict:
      total_terrible, total_escaped, escape_rate, runs_stolen,
      grade, top_escapes, by_type, low_sample.
    """
    if pitch_type_filter:
        rows = [r for r in rows if r.get("pitch_type", "").strip() == pitch_type_filter]

    pt_averages = _compute_pt_averages(rows)

    terrible: list[dict] = []
    for row in rows:
        badness = _pitch_badness(row, pt_averages)
        if badness is None or badness < _MIN_BADNESS:
            continue
        escape_rv = _escape_run_value(row)
        if escape_rv is None:
            continue

        lev = _leverage(row)
        terrible.append({
            "row":         row,
            "badness":     badness,
            "escape_rv":   escape_rv,
            "weighted_rv": escape_rv * lev,
            "escaped":     escape_rv > 0,
        })

    if not terrible:
        return {
            "total_terrible": 0, "total_escaped": 0, "escape_rate": 0.0,
            "runs_stolen": 0.0, "grade": ("N/A", "No data"),
            "top_escapes": [], "by_type": {}, "low_sample": True,
        }

    total   = len(terrible)
    escaped = [p for p in terrible if p["escaped"]]
    escape_rate = len(escaped) / total * 100
    runs_stolen = sum(p["weighted_rv"] for p in escaped)

    # Top moments: worst pitch × best escape
    escaped_sorted = sorted(
        escaped,
        key=lambda p: p["badness"] * p["escape_rv"],
        reverse=True,
    )[:5]

    top_escapes = []
    for p in escaped_sorted:
        row = p["row"]
        pt       = row.get("pitch_type", "").strip()
        velo     = _to_float(row.get("release_speed"))
        avg_v    = pt_averages.get(pt, {}).get("avg_velo", 0.0)
        plate_x  = _to_float(row.get("plate_x"))
        plate_z  = _to_float(row.get("plate_z"))
        sz_top   = _to_float(row.get("sz_top"))
        sz_bot   = _to_float(row.get("sz_bot"))
        desc     = row.get("description", "").strip()
        events   = row.get("events",      "").strip()

        zone_desc = ""
        if all(v is not None for v in (plate_x, plate_z, sz_top, sz_bot)):
            zone_desc = _format_zone_desc(
                plate_x, plate_z, sz_top, sz_bot  # type: ignore[arg-type]
            )

        # Break delta vs pitcher's average
        pfx_x = _to_float(row.get("pfx_x"))
        pfx_z = _to_float(row.get("pfx_z"))
        break_delta: Optional[float] = None
        avg_break = pt_averages.get(pt, {}).get("avg_break_in", 0.0)
        if pfx_x is not None and pfx_z is not None and avg_break > 0:
            total_brk   = math.sqrt((pfx_x * 12) ** 2 + (pfx_z * 12) ** 2)
            break_delta = total_brk - avg_break

        # Human-readable outcome
        if desc in ("swinging_strike", "swinging_strike_blocked", "foul_tip"):
            outcome = "Swing and miss"
        elif desc == "called_strike":
            outcome = "Called strike"
        elif desc in ("foul", "foul_bunt"):
            outcome = "Fouled off"
        elif desc.startswith("hit_into_play"):
            ev = _to_float(row.get("launch_speed"))
            if events:
                outcome = events.replace("_", " ").title()
                if ev:
                    outcome += f" ({ev:.0f} mph EV)"
            else:
                outcome = "Ball in play" + (f" ({ev:.0f} mph EV)" if ev else "")
        else:
            outcome = desc.replace("_", " ").title() if desc else "—"

        top_escapes.append({
            "date":        str(row.get("game_date", ""))[:10],
            "pitch_type":  pt,
            "label":       PITCH_TYPE_LABELS.get(pt, pt),
            "velo":        velo,
            "velo_delta":  (velo - avg_v) if (velo and avg_v) else None,
            "zone_desc":   zone_desc,
            "break_delta": break_delta,
            "outcome":     outcome,
            "escape_rv":   p["escape_rv"],
            "badness":     p["badness"],
            "count":       f"{_to_int(row.get('balls', 0))}-{_to_int(row.get('strikes', 0))}",
            "inning":      _to_int(row.get("inning", 0)),
        })

    # Per-pitch-type breakdown (only types with ≥5 terrible pitches)
    by_type: dict[str, dict] = defaultdict(lambda: {"total": 0, "escaped": 0, "runs": 0.0})
    for p in terrible:
        pt = p["row"].get("pitch_type", "").strip()
        by_type[pt]["total"] += 1
        if p["escaped"]:
            by_type[pt]["escaped"] += 1
            by_type[pt]["runs"] += p["weighted_rv"]

    by_type_clean = {pt: v for pt, v in by_type.items() if v["total"] >= 5}

    return {
        "total_terrible": total,
        "total_escaped":  len(escaped),
        "escape_rate":    escape_rate,
        "runs_stolen":    runs_stolen,
        "grade":          _grade(escape_rate),
        "top_escapes":    top_escapes,
        "by_type":        by_type_clean,
        "low_sample":     total < _MIN_TERRIBLE,
    }


def _season_note() -> str:
    if is_spring_training():
        return "🌸 Spring Training data"
    if is_early_regular_season():
        return "🔶 Early season — small samples"
    return ""


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class GetAwayCog(commands.Cog, name="GetAway"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="getaway",
        description=(
            "How well does a pitcher escape terrible pitches? "
            "Scores location, break, velocity, and RE24 outcome."
        ),
    )
    @app_commands.describe(
        pitcher="Pitcher name (select from pitchers with available data)",
        pitch_type="Optional: filter analysis to a specific pitch type",
    )
    @app_commands.choices(pitch_type=_PITCH_CHOICES)
    async def getaway(
        self,
        interaction: discord.Interaction,
        pitcher: str,
        pitch_type: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await interaction.response.defer()

        mlbam_id, full_name, error = resolve_player(pitcher, require_pitcher=True)
        if error:
            await interaction.followup.send(f"**Error:** {error}", ephemeral=True)
            return

        rows = await asyncio.to_thread(get_pitcher_statcast, mlbam_id)
        if not rows:
            await interaction.followup.send(
                f"**No Statcast data found for {full_name} this season.**",
                ephemeral=True,
            )
            return

        pt_filter = pitch_type.value if pitch_type else None
        pt_label  = pitch_type.name  if pitch_type else None

        result = await asyncio.to_thread(_analyze_getaway, rows, pt_filter)

        title_suffix = f" — {pt_label}" if pt_label else ""
        embed = discord.Embed(
            title=f"🎲 {full_name} — Getting Away With It{title_suffix}",
            color=PHILLIES_RED,
        )

        total       = result["total_terrible"]
        escaped     = result["total_escaped"]
        escape_rate = result["escape_rate"]
        runs_stolen = result["runs_stolen"]
        letter, label = result["grade"]

        if total == 0:
            embed.description = (
                "_No terrible pitches identified — either this pitcher locates "
                "exceptionally well or there is insufficient Statcast data._"
            )
            note = _season_note()
            embed.set_footer(
                text=(f"{note} · " if note else "") + "Phillies Therapy Bot"
            )
            await interaction.followup.send(embed=embed)
            return

        sample_note = " ⚠️ *small sample*" if result["low_sample"] else ""
        embed.description = (
            f"**Terrible Pitches:** {total} · "
            f"**Escaped:** {escaped} ({escape_rate:.1f}%){sample_note}\n"
            f"**Runs Stolen (RE24-weighted):** +{runs_stolen:.2f}\n"
            f"**Grade: {letter}** — {label}"
        )

        # ── Top individual escapes ───────────────────────────────────────────
        top = result["top_escapes"]
        if top:
            lines = []
            for i, e in enumerate(top, 1):
                # Velocity line
                velo_str = f"{e['velo']:.1f} mph" if e["velo"] else ""
                if e["velo_delta"] is not None:
                    sign = "+" if e["velo_delta"] >= 0 else ""
                    velo_str += f" ({sign}{e['velo_delta']:.1f})"

                # Break vs average
                brk_str = ""
                if e["break_delta"] is not None:
                    sign = "+" if e["break_delta"] >= 0 else ""
                    brk_str = f" · Break {sign}{e['break_delta']:.1f} in"

                count_str = (
                    f" · {e['count']} count" if e["count"] not in ("0-0", "") else ""
                )
                inn_str = f" · Inn {e['inning']}" if e["inning"] else ""

                line = (
                    f"**{i}. {e['date']}** — {e['label']}"
                    + (f" · {velo_str}" if velo_str else "")
                    + (f"\n   📍 {e['zone_desc']}" if e["zone_desc"] else "")
                    + brk_str
                    + f"\n   ↳ {e['outcome']}{count_str}{inn_str}"
                    + f" · RE saved: {e['escape_rv']:+.2f} · Badness: {e['badness']:.0f}"
                )
                lines.append(line)

            field_val = "\n".join(lines)
            if len(field_val) > 1024:
                field_val = field_val[:1021] + "..."
            embed.add_field(name="💀 Top Gets Away", value=field_val, inline=False)

        # ── Per-pitch-type breakdown ─────────────────────────────────────────
        by_type = result["by_type"]
        if len(by_type) >= 2:
            type_lines = []
            for pt, stats in sorted(by_type.items(), key=lambda x: -x[1]["total"]):
                lbl  = PITCH_TYPE_LABELS.get(pt, pt)
                t    = stats["total"]
                esc  = stats["escaped"]
                rate = esc / t * 100 if t else 0.0
                runs = stats["runs"]
                type_lines.append(
                    f"**{lbl}:** {t} terrible, {esc} escaped "
                    f"({rate:.0f}%) · +{runs:.2f} runs"
                )
            type_val = "\n".join(type_lines)
            if len(type_val) > 1024:
                type_val = type_val[:1021] + "..."
            embed.add_field(name="📊 By Pitch Type", value=type_val, inline=False)

        note = _season_note()
        footer_parts = [
            "Badness: 60% location · 20% movement · 20% velocity",
            note,
            "Phillies Therapy Bot",
        ]
        embed.set_footer(text=" · ".join(p for p in footer_parts if p))
        await interaction.followup.send(embed=embed)

    @getaway.autocomplete("pitcher")
    async def getaway_pitcher_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Return pitchers with 1+ recorded PAR starts, sorted A-Z by last name."""
        spgrader = self.bot.cogs.get("SPGrader")
        if spgrader is None:
            return []

        seen: dict[int, str] = {}
        for r in spgrader.monitor.leaderboard._records:
            seen[r.pitcher_id] = r.pitcher_name

        def _last_name(name: str) -> str:
            parts = name.strip().split()
            return parts[-1].lower() if parts else name.lower()

        pitchers = sorted(seen.values(), key=_last_name)
        if current:
            pitchers = [p for p in pitchers if current.lower() in p.lower()]

        return [app_commands.Choice(name=p, value=p) for p in pitchers[:25]]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GetAwayCog(bot))
