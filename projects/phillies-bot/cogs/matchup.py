"""
Cog: /matchup slash command.

Focuses on the next Phillies game's starting pitcher matchup.
Cross-references each SP's Statcast pitch arsenal (velocity, movement, whiff
rate, usage) with opposing hitter tendencies and individual batter spotlights.
Includes a rolling 30-day recent-form comparison vs. season-to-date.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import discord
import statsapi
from discord import app_commands
from discord.ext import commands

from cogs.trends import _compute_pitcher_metrics, _safe_mean, _SWINGING_DESCS
from utils.mlb_data import (
    PITCH_TYPE_LABELS,
    _get_phillies_batter_statcast,
    _to_float,
    _to_int,
    fetch_statcast_for_range,
    get_next_game_with_probables,
    get_opponent_roster_batters,
    get_phillies_roster_full,
    get_pitcher_statcast,
)

PHILLIES_RED = 0xE81828
_RECENT_DAYS = 30
_MIN_SEASON_PITCHES = 30   # min pitches per type to show in arsenal
_MIN_RECENT_PITCHES = 15   # min pitches per type for delta indicators
_MIN_HITTER_PITCHES = 8    # min pitches seen by a hitter for spotlight
_MIN_PHI_PA = 10           # min PHI PA vs opp SP for direct history


# ---------------------------------------------------------------------------
# Pure analysis helpers
# ---------------------------------------------------------------------------

def _contact_quality(rows: list[dict]) -> dict[str, dict]:
    """
    Per pitch type: xBA allowed, avg EV allowed, hard-hit rate.
    Only rows with a non-null launch_speed (i.e., balls in play) are counted.
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        pt = row.get("pitch_type", "").strip()
        ev = _to_float(row.get("launch_speed"))
        if pt and ev is not None and ev > 0:
            by_type[pt].append(row)

    result: dict[str, dict] = {}
    for pt, bip_rows in by_type.items():
        evs = [_to_float(r.get("launch_speed")) for r in bip_rows]
        evs = [v for v in evs if v is not None and v > 0]
        xbas = [_to_float(r.get("estimated_ba_using_speedangle")) for r in bip_rows]
        xbas = [v for v in xbas if v is not None]
        result[pt] = {
            "n_bip": len(evs),
            "avg_ev": _safe_mean(evs),
            "xba": _safe_mean(xbas),
            "hard_hit": sum(1 for e in evs if e >= 95) / len(evs) * 100 if evs else None,
        }
    return result


def _hitter_vs_pitcher(
    pitcher_rows: list[dict],
    hitter_ids: set[int],
) -> dict[int, dict]:
    """
    For each batter in hitter_ids, compute per-pitch-type and overall metrics
    against this pitcher's season rows.

    Returns: {batter_id: {"total": n, "by_type": {pt: {n, whiff, xba, avg_ev}}}}
    """
    by_batter: dict[int, list[dict]] = defaultdict(list)
    for row in pitcher_rows:
        bid = _to_int(row.get("batter", 0))
        if bid in hitter_ids:
            by_batter[bid].append(row)

    result: dict[int, dict] = {}
    for bid, rows in by_batter.items():
        if len(rows) < _MIN_HITTER_PITCHES:
            continue
        by_type: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            pt = row.get("pitch_type", "").strip()
            if pt:
                by_type[pt].append(row)

        pt_stats: dict[str, dict] = {}
        for pt, pt_rows in by_type.items():
            n = len(pt_rows)
            swings = sum(
                1 for r in pt_rows
                if r.get("description", "").strip() in _SWINGING_DESCS
            )
            evs = [_to_float(r.get("launch_speed")) for r in pt_rows]
            evs = [v for v in evs if v is not None and v > 0]
            xbas = [_to_float(r.get("estimated_ba_using_speedangle")) for r in pt_rows]
            xbas = [v for v in xbas if v is not None]
            pt_stats[pt] = {
                "n": n,
                "whiff": swings / n * 100,
                "avg_ev": _safe_mean(evs),
                "xba": _safe_mean(xbas),
            }

        result[bid] = {"total": len(rows), "by_type": pt_stats}
    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _abbrev_name(full: str) -> str:
    """'Zack Wheeler' → 'Z. Wheeler'"""
    parts = full.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"
    return full


def _delta_str(season_val: Optional[float], recent_val: Optional[float], decimals: int = 1) -> str:
    """Return ' (+0.3)' / ' (-1.2)' or '' if insufficient data."""
    if season_val is None or recent_val is None:
        return ""
    delta = recent_val - season_val
    sign = "+" if delta >= 0 else ""
    return f" ({sign}{delta:.{decimals}f})"


def _break_str(h: Optional[float], v: Optional[float]) -> str:
    """Format horizontal + vertical break as '→8.1/↑14.2 in'."""
    if h is None and v is None:
        return ""
    parts = []
    if h is not None:
        arrow = "→" if h >= 0 else "←"
        parts.append(f"{arrow}{abs(h):.1f}")
    if v is not None:
        arrow = "↑" if v >= 0 else "↓"
        parts.append(f"{arrow}{abs(v):.1f}")
    return "/".join(parts) + " in"


def _arsenal_text(season_rows: list[dict], recent_rows: list[dict]) -> str:
    """
    Build the Arsenal & Recent Form field text for one pitcher.
    Returns a string suitable for a Discord embed field value.
    """
    season_m = _compute_pitcher_metrics(season_rows)
    recent_m = _compute_pitcher_metrics(recent_rows) if recent_rows else {}
    cq = _contact_quality(season_rows)

    by_type = season_m.get("by_type", {})
    if not by_type:
        return "_No Statcast data available for this pitcher yet._"

    # Sort by usage descending, keep top 5
    sorted_types = sorted(
        [(pt, m) for pt, m in by_type.items() if m.get("n", 0) >= _MIN_SEASON_PITCHES],
        key=lambda x: x[1].get("usage_pct", 0),
        reverse=True,
    )[:5]

    if not sorted_types:
        return "_Insufficient Statcast data (< 30 pitches per type)._"

    recent_by_type = recent_m.get("by_type", {}) if recent_m else {}
    lines = []
    contact_lines = []

    for pt, sm in sorted_types:
        label = PITCH_TYPE_LABELS.get(pt, pt)
        usage = sm.get("usage_pct")
        velo = sm.get("velocity")
        hb = sm.get("h_break")
        vb = sm.get("v_break")
        whiff = sm.get("whiff_rate")

        rm_raw = recent_by_type.get(pt)
        rm = rm_raw if (rm_raw and rm_raw.get("n", 0) >= _MIN_RECENT_PITCHES) else {}

        # Arsenal line: pitch | velocity (delta) | break | whiff (delta) | usage
        parts = [f"**{label}**"]
        if usage is not None:
            parts.append(f"{usage:.0f}% usage")
        if velo is not None:
            vd = _delta_str(velo, rm.get("velocity"))
            parts.append(f"{velo:.1f} mph{vd}")
        brk = _break_str(hb, vb)
        if brk:
            parts.append(brk)
        if whiff is not None:
            wd = _delta_str(whiff, rm.get("whiff_rate"))
            parts.append(f"{whiff:.1f}% whiff{wd}")

        lines.append(" · ".join(parts))

        # Contact quality line
        cq_pt = cq.get(pt)
        if cq_pt and cq_pt.get("n_bip", 0) >= 5:
            cparts = []
            if cq_pt.get("xba") is not None:
                cparts.append(f".{round(cq_pt['xba'] * 1000):03d} xBA")
            if cq_pt.get("avg_ev") is not None:
                cparts.append(f"{cq_pt['avg_ev']:.1f} mph avgEV")
            if cq_pt.get("hard_hit") is not None:
                cparts.append(f"{cq_pt['hard_hit']:.0f}% HH")
            if cparts:
                contact_lines.append(f"  ↳ *Contact vs {label}:* {' · '.join(cparts)}")

    text = "\n".join(lines)
    if contact_lines:
        text += "\n" + "\n".join(contact_lines)
    return text


def _hitter_spotlight_text(
    pitcher_rows: list[dict],
    roster: list[dict],
    perspective: str = "pitcher",  # "pitcher" = SP is threat; "hitter" = batter is threat
) -> str:
    """
    Build the hitter spotlight field text.

    perspective="pitcher" → flag hitters who struggle (high whiff, low xBA) = 🚨 weakness
                            and hitters who thrive (high xBA, low whiff)    = ⚠️ danger
    perspective="hitter"  → flag PHI hitters who thrive vs this SP          = 💪 strength
                            and those who struggle                           = 🎯 target
    """
    roster_map = {p["id"]: p for p in roster}
    roster_ids = set(roster_map.keys())

    stats = _hitter_vs_pitcher(pitcher_rows, roster_ids)
    if not stats:
        return "_No prior matchup data available._"

    # For each hitter, find their best/worst pitch-type matchup by xBA
    scored: list[dict] = []
    for bid, data in stats.items():
        info = roster_map.get(bid)
        if not info:
            continue
        by_type = data.get("by_type", {})
        if not by_type:
            continue

        # Find the pitch type with most data for this hitter
        best_pt = max(by_type, key=lambda pt: by_type[pt]["n"])
        best = by_type[best_pt]

        scored.append({
            "bid": bid,
            "name": info["fullName"],
            "pos": info.get("position", ""),
            "total_n": data["total"],
            "best_pt": best_pt,
            "whiff": best.get("whiff"),
            "xba": best.get("xba"),
            "avg_ev": best.get("avg_ev"),
            "n": best["n"],
            "all_types": by_type,
        })

    if not scored:
        return "_No prior matchup data available._"

    # Sort by total pitches seen (most data first), take top 5 for analysis
    scored.sort(key=lambda x: x["total_n"], reverse=True)
    top = scored[:5]

    lines = []
    for h in top:
        name_abbr = _abbrev_name(h["name"])
        pos = h["pos"]
        pt_label = PITCH_TYPE_LABELS.get(h["best_pt"], h["best_pt"])

        # Choose icon based on perspective
        xba = h.get("xba")
        whiff = h.get("whiff")
        if perspective == "pitcher":
            # High whiff = hitter vulnerable 🚨; high xBA = danger for pitcher ⚠️
            if whiff is not None and whiff >= 30:
                icon = "🚨"
                descriptor = "vulnerable"
            elif xba is not None and xba >= 0.300:
                icon = "⚠️"
                descriptor = "danger"
            else:
                icon = "📊"
                descriptor = "tracked"
        else:
            # High xBA = PHI hitter strength 💪; high whiff = target 🎯
            if xba is not None and xba >= 0.280:
                icon = "💪"
                descriptor = "strength"
            elif whiff is not None and whiff >= 30:
                icon = "🎯"
                descriptor = "target"
            else:
                icon = "📊"
                descriptor = "tracked"

        stat_parts = []
        if whiff is not None:
            stat_parts.append(f"{whiff:.0f}% whiff")
        if xba is not None:
            stat_parts.append(f".{round(xba * 1000):03d} xBA")
        if h.get("avg_ev") is not None:
            stat_parts.append(f"{h['avg_ev']:.1f} avgEV")

        stat_str = " · ".join(stat_parts) if stat_parts else "—"
        lines.append(
            f"{icon} **{name_abbr}** ({pos}) vs {pt_label} — {stat_str} _(n={h['n']})_"
        )

    return "\n".join(lines) if lines else "_No prior matchup data available._"


def _phi_vs_sp_text(phi_bat_rows: list[dict], opp_sp_id: int, phi_roster: list[dict]) -> str:
    """
    PHI hitter performance specifically against the opponent SP.
    Filters season PHI batter rows by pitcher == opp_sp_id.
    Falls back gracefully if insufficient history.
    """
    sp_rows = [
        r for r in phi_bat_rows
        if _to_int(r.get("pitcher", 0)) == opp_sp_id
    ]

    if len(sp_rows) < _MIN_PHI_PA:
        note = (
            f"_Limited prior history (n={len(sp_rows)} PA) — showing PHI team tendencies._\n"
            if sp_rows else
            "_No prior history vs this pitcher this season._\n"
        )
        if not sp_rows:
            return note.strip()
        # Fall through with what we have and note the caveat
    else:
        note = ""

    phi_roster_map = {p["id"]: p for p in phi_roster}
    phi_ids = set(phi_roster_map.keys())
    spotlight = _hitter_spotlight_text(
        # Treat the filtered SP rows as the "pitcher_rows" — they already contain
        # only pitches from opp_sp_id, so we can analyze by batter
        sp_rows,
        phi_roster,
        perspective="hitter",
    )
    return note + spotlight


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class MatchupCog(commands.Cog, name="Matchup"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="matchup",
        description="Pitcher matchup analysis for the next Phillies game",
    )
    async def matchup(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        # ── Step 1: Find next game ────────────────────────────────────────────
        game = await asyncio.to_thread(get_next_game_with_probables)

        if game is None:
            embed = discord.Embed(
                title="⚾ Matchup Analysis",
                description="No upcoming Phillies games found in the next 10 days.",
                color=PHILLIES_RED,
            )
            await interaction.followup.send(embed=embed)
            return

        opp = game["opponent"]
        game_date = game["game_date"]
        venue = "@ " + opp["abbreviation"] if game["phi_is_home"] is False else "vs " + opp["abbreviation"]

        phi_prob = game.get("phi_probable")
        opp_prob = game.get("opp_probable")

        embed = discord.Embed(
            title=f"⚾ Matchup Analysis — {game_date}",
            color=PHILLIES_RED,
        )

        phi_sp_str = phi_prob["fullName"] if phi_prob else "TBD"
        opp_sp_str = opp_prob["fullName"] if opp_prob else "TBD"
        embed.description = (
            f"**PHI {venue} {opp['name']}**\n"
            f"🔴 {phi_sp_str}  vs  ⚔️ {opp_sp_str}"
        )

        if not phi_prob and not opp_prob:
            embed.add_field(
                name="Probable Pitchers",
                value="_Not yet announced. Check back closer to game time._",
                inline=False,
            )
            embed.set_footer(text="Phillies Therapy Bot")
            await interaction.followup.send(embed=embed)
            return

        # ── Step 2: Fetch Statcast data concurrently ──────────────────────────
        today_str = date.today().isoformat()
        window_start = (date.today() - timedelta(days=_RECENT_DAYS)).isoformat()

        async def _fetch_pitcher(pid: int):
            season = await asyncio.to_thread(get_pitcher_statcast, pid)
            recent = await asyncio.to_thread(
                fetch_statcast_for_range, pid, "pitcher", window_start, today_str
            )
            return season, recent

        tasks = []
        if phi_prob:
            tasks.append(_fetch_pitcher(phi_prob["id"]))
        if opp_prob:
            tasks.append(_fetch_pitcher(opp_prob["id"]))

        results = await asyncio.gather(*tasks)

        phi_season, phi_recent = results[0] if phi_prob else ([], [])
        if phi_prob and opp_prob:
            opp_season, opp_recent = results[1]
        elif opp_prob and not phi_prob:
            opp_season, opp_recent = results[0]
        else:
            opp_season, opp_recent = [], []

        phi_bat_rows = await asyncio.to_thread(_get_phillies_batter_statcast)

        opp_roster = []
        phi_roster_full = []
        if opp_prob and opp["id"]:
            opp_roster, phi_roster_full = await asyncio.gather(
                asyncio.to_thread(get_opponent_roster_batters, opp["id"]),
                asyncio.to_thread(get_phillies_roster_full),
            )
        elif phi_prob:
            phi_roster_full = await asyncio.to_thread(get_phillies_roster_full)

        phi_hitter_roster = [p for p in phi_roster_full if not p.get("is_pitcher")]

        # ── Step 3–4: PHI SP arsenal + contact quality ────────────────────────
        if phi_prob:
            phi_arsenal = await asyncio.to_thread(
                _arsenal_text, phi_season, phi_recent
            )
            embed.add_field(
                name=f"🔴 {phi_prob['fullName']} — Arsenal & Recent Form (last {_RECENT_DAYS}d)",
                value=phi_arsenal[:1024],
                inline=False,
            )

            # ── Step 5: PHI SP hitter spotlights (opponent hitters) ───────────
            if opp_roster and phi_season:
                phi_sp_spotlights = await asyncio.to_thread(
                    _hitter_spotlight_text, phi_season, opp_roster, "pitcher"
                )
            else:
                phi_sp_spotlights = "_Opponent roster data unavailable._"
            embed.add_field(
                name=f"🔴 {phi_prob['fullName']} — Hitter Spotlights (vs {opp['abbreviation']})",
                value=phi_sp_spotlights[:1024],
                inline=False,
            )

        # ── Step 3–4: OPP SP arsenal + contact quality ────────────────────────
        if opp_prob:
            opp_arsenal = await asyncio.to_thread(
                _arsenal_text, opp_season, opp_recent
            )
            embed.add_field(
                name=f"⚔️ {opp_prob['fullName']} — Arsenal & Recent Form (last {_RECENT_DAYS}d)",
                value=opp_arsenal[:1024],
                inline=False,
            )

            # ── Step 6: PHI hitters vs opponent SP ───────────────────────────
            if phi_hitter_roster and phi_bat_rows:
                phi_vs_opp = await asyncio.to_thread(
                    _phi_vs_sp_text, phi_bat_rows, opp_prob["id"], phi_hitter_roster
                )
            else:
                phi_vs_opp = "_PHI batter data unavailable._"
            embed.add_field(
                name=f"⚔️ {opp_prob['fullName']} — PHI Hitter Spotlights",
                value=phi_vs_opp[:1024],
                inline=False,
            )

        embed.set_footer(
            text=(
                f"Last {_RECENT_DAYS}d window · Statcast via Baseball Savant · "
                "Phillies Therapy Bot"
            )
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MatchupCog(bot))
