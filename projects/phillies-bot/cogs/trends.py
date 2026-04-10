"""
Cog: /trends slash command.

Compares a Phillies player's Statcast metrics over the selected window
(last 7 / 14 / 30 days) against the prior equal-length window.
Surfaces up to 3 trends that cross meaningful significance thresholds.

  - Hitters: exit velocity, whiff rate, hard-hit rate, xBA, sweet-spot %
  - Pitchers: per-pitch-type velocity, horizontal/vertical break, spin rate,
              whiff rate, usage %
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from datetime import date, timedelta
from collections import defaultdict
from typing import Optional

from utils.mlb_data import (
    get_phillies_roster_full,
    fetch_statcast_for_range,
    _to_float,
    PITCH_TYPE_LABELS,
)

PHILLIES_RED = 0xE81828

# ─── Minimum samples ──────────────────────────────────────────────────────────
_MIN_BIP = 10           # min balls in play for EV / xBA / sweet-spot metrics
_MIN_PITCHES_SEEN = 20  # min pitches seen for hitter whiff rate
_MIN_PT_PITCHES = 10    # min pitches of a given type for pitcher per-type metrics

# ─── Significance thresholds ──────────────────────────────────────────────────
# A trend is only surfaced when |delta| >= threshold.

_HITTER_THRESHOLDS: dict[str, float] = {
    "avg_ev":         3.0,   # mph
    "whiff_rate":     5.0,   # percentage points
    "hard_hit_rate":  8.0,   # pp
    "xba_avg":        0.025, # raw xBA
    "sweet_spot_pct": 8.0,   # pp
}

_PITCHER_THRESHOLDS: dict[str, float] = {
    "velocity":   1.0,    # mph
    "h_break":    2.0,    # inches
    "v_break":    2.0,    # inches
    "whiff_rate": 8.0,    # pp
    "usage_pct":  8.0,    # pp
    "spin_rate":  150.0,  # rpm
}

# ─── Display metadata ─────────────────────────────────────────────────────────
# (label, unit, up_is_bad_for_player)   None = directionally neutral
_HITTER_META: dict[str, tuple[str, str, Optional[bool]]] = {
    "avg_ev":         ("Avg Exit Velocity",  "mph",  False),
    "whiff_rate":     ("Whiff Rate",         "%",    True),
    "hard_hit_rate":  ("Hard Hit Rate",      "%",    False),
    "xba_avg":        ("Avg xBA",            "",     False),
    "sweet_spot_pct": ("Sweet Spot %",       "%",    False),
}

_PITCHER_META: dict[str, tuple[str, str, Optional[bool]]] = {
    "velocity":   ("Velocity",                 "mph", False),
    "h_break":    ("Horizontal Break",         "in",  None),
    "v_break":    ("Vertical Break (induced)", "in",  None),
    "whiff_rate": ("Whiff Rate",               "%",   False),
    "usage_pct":  ("Usage %",                  "%",   None),
    "spin_rate":  ("Spin Rate",                "rpm", None),
}

_SWINGING_DESCS = {"swinging_strike", "swinging_strike_blocked", "foul_tip"}


# ─── Metric computation ───────────────────────────────────────────────────────

def _safe_mean(vals: list[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _compute_hitter_metrics(rows: list[dict]) -> dict:
    """Aggregate hitter Statcast rows into metric dict."""
    if not rows:
        return {}

    pitches_seen = len(rows)
    swings = 0
    evs: list[float] = []
    xbas: list[float] = []
    las: list[float] = []

    for row in rows:
        desc = row.get("description", "").strip()
        if desc in _SWINGING_DESCS:
            swings += 1

        ev = _to_float(row.get("launch_speed"))
        la = _to_float(row.get("launch_angle"))
        xba = _to_float(row.get("estimated_ba_using_speedangle"))

        if ev is not None and ev > 0:
            evs.append(ev)
            if la is not None:
                las.append(la)
            if xba is not None:
                xbas.append(xba)

    bip = len(evs)
    m: dict = {"pitches_seen": pitches_seen, "bip": bip}

    if pitches_seen >= _MIN_PITCHES_SEEN:
        m["whiff_rate"] = swings / pitches_seen * 100

    if bip >= _MIN_BIP:
        m["avg_ev"] = _safe_mean(evs)
        m["hard_hit_rate"] = sum(1 for e in evs if e >= 95) / bip * 100
        if xbas:
            m["xba_avg"] = _safe_mean(xbas)
        if las:
            m["sweet_spot_pct"] = sum(1 for a in las if 8 <= a <= 32) / len(las) * 100

    return m


def _compute_pitcher_metrics(rows: list[dict]) -> dict:
    """Aggregate pitcher Statcast rows into per-pitch-type metric dict."""
    if not rows:
        return {}

    total = len(rows)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        pt = row.get("pitch_type", "").strip()
        if pt:
            by_type[pt].append(row)

    # Count only rows that carry a pitch-type label.  Savant can return
    # unclassified rows early in the season while pitch classification is still
    # being processed, inflating total_pitches without contributing usable data.
    typed_total = sum(1 for r in rows if r.get("pitch_type", "").strip())

    by_type_metrics: dict[str, dict] = {}
    for pt, pt_rows in by_type.items():
        n = len(pt_rows)
        if n < _MIN_PT_PITCHES:
            continue

        velos = [v for v in (_to_float(r.get("release_speed")) for r in pt_rows)
                 if v is not None and v > 0]
        # pfx values are in feet — convert to inches
        hbs = [v * 12 for v in (_to_float(r.get("pfx_x")) for r in pt_rows)
               if v is not None]
        vbs = [v * 12 for v in (_to_float(r.get("pfx_z")) for r in pt_rows)
               if v is not None]
        spins = [v for v in (_to_float(r.get("release_spin_rate")) for r in pt_rows)
                 if v is not None and v > 0]
        swings = sum(1 for r in pt_rows
                     if r.get("description", "").strip() in _SWINGING_DESCS)

        denom = typed_total if typed_total > 0 else total
        pm: dict = {
            "n": n,
            "usage_pct": n / denom * 100,
            "whiff_rate": swings / n * 100,
        }
        if velos:
            pm["velocity"] = _safe_mean(velos)
        if hbs:
            pm["h_break"] = _safe_mean(hbs)
        if vbs:
            pm["v_break"] = _safe_mean(vbs)
        if spins:
            pm["spin_rate"] = _safe_mean(spins)

        by_type_metrics[pt] = pm

    return {"total_pitches": total, "typed_pitches": typed_total, "by_type": by_type_metrics}


# ─── Trend detection ──────────────────────────────────────────────────────────

def _find_hitter_trends(win: dict, prior: dict) -> list[dict]:
    """Return up to 3 hitter trends sorted by relative significance."""
    trends = []
    for key, threshold in _HITTER_THRESHOLDS.items():
        w = win.get(key)
        p = prior.get(key)
        if w is None or p is None:
            continue
        delta = w - p
        if abs(delta) < threshold:
            continue
        sample_key = "pitches_seen" if key == "whiff_rate" else "bip"
        trends.append({
            "key": key,
            "delta": delta,
            "window_val": w,
            "prior_val": p,
            "n": win.get(sample_key, 0),
            "significance": abs(delta) / threshold,
        })
    trends.sort(key=lambda t: t["significance"], reverse=True)
    return trends[:3]


def _find_pitcher_trends(win: dict, prior: dict) -> list[dict]:
    """Return up to 3 pitcher per-pitch-type trends sorted by relative significance."""
    win_types = win.get("by_type", {})
    prior_types = prior.get("by_type", {})
    trends = []
    for pt, wm in win_types.items():
        pm = prior_types.get(pt)
        if pm is None:
            continue
        for key, threshold in _PITCHER_THRESHOLDS.items():
            wv = wm.get(key)
            pv = pm.get(key)
            if wv is None or pv is None:
                continue
            delta = wv - pv
            if abs(delta) < threshold:
                continue
            trends.append({
                "pitch_type": pt,
                "key": key,
                "delta": delta,
                "window_val": wv,
                "prior_val": pv,
                "n": wm.get("n", 0),
                "significance": abs(delta) / threshold,
            })
    trends.sort(key=lambda t: t["significance"], reverse=True)
    return trends[:3]


# ─── Formatting ───────────────────────────────────────────────────────────────

def _fmt_val(val: float, unit: str) -> str:
    if unit == "mph":
        return f"{val:.1f} mph"
    if unit == "%":
        return f"{val:.1f}%"
    if unit == "rpm":
        return f"{val:.0f} rpm"
    if unit == "in":
        return f"{val:.1f} in"
    if unit == "":
        return f"{val:.3f}"
    return str(round(val, 2))


def _trend_icon(delta: float, up_is_bad: Optional[bool]) -> str:
    """Return a directional emoji.  None = neutral (show 📊)."""
    if up_is_bad is None:
        return "📊"
    going_up = delta > 0
    good = not going_up if up_is_bad else going_up
    return "📈" if good else "📉"


def _hitter_trend_line(t: dict) -> str:
    label, unit, up_is_bad = _HITTER_META[t["key"]]
    icon = _trend_icon(t["delta"], up_is_bad)
    sign = "+" if t["delta"] > 0 else ""
    delta_str = (f"{sign}{t['delta']:.3f}" if unit == ""
                 else f"{sign}{t['delta']:.1f}{unit}")
    return (
        f"{icon} **{label}** {delta_str}\n"
        f"  Window: **{_fmt_val(t['window_val'], unit)}**  |  "
        f"Prior: {_fmt_val(t['prior_val'], unit)}  _(n={t['n']})_"
    )


def _pitcher_trend_line(t: dict) -> str:
    pt_label = PITCH_TYPE_LABELS.get(t["pitch_type"], t["pitch_type"])
    label, unit, up_is_bad = _PITCHER_META[t["key"]]
    icon = _trend_icon(t["delta"], up_is_bad)
    sign = "+" if t["delta"] > 0 else ""
    delta_str = (f"{sign}{t['delta']:.0f}{unit}" if unit == "rpm"
                 else f"{sign}{t['delta']:.1f}{unit}")
    return (
        f"{icon} **{pt_label} — {label}** {delta_str}\n"
        f"  Window: **{_fmt_val(t['window_val'], unit)}**  |  "
        f"Prior: {_fmt_val(t['prior_val'], unit)}  _(n={t['n']} pitches)_"
    )


# ─── Cog ──────────────────────────────────────────────────────────────────────

class TrendsCog(commands.Cog, name="Trends"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _roster(self) -> list[dict]:
        """Sorted 40-man roster (last-name A-Z)."""
        players = get_phillies_roster_full()

        def _last(name: str) -> str:
            parts = name.strip().split()
            return parts[-1].lower() if parts else name.lower()

        return sorted(players, key=lambda p: _last(p["fullName"]))

    def _resolve_player(self, name: str) -> Optional[dict]:
        """Find a roster entry by exact or case-insensitive name match."""
        roster = get_phillies_roster_full()
        name_lower = name.strip().lower()
        for p in roster:
            if p["fullName"].lower() == name_lower:
                return p
        # Fallback: partial match
        for p in roster:
            if name_lower in p["fullName"].lower():
                return p
        return None

    def _date_windows(self, days: int) -> tuple[str, str, str, str]:
        """Return (win_start, win_end, prior_start, prior_end) as ISO strings."""
        today = date.today()
        win_start = (today - timedelta(days=days)).isoformat()
        win_end = today.isoformat()
        prior_start = (today - timedelta(days=2 * days)).isoformat()
        prior_end = (today - timedelta(days=days + 1)).isoformat()
        return win_start, win_end, prior_start, prior_end

    # ── /trends ───────────────────────────────────────────────────────────────

    @app_commands.command(
        name="trends",
        description="Spot recent Statcast trends for a Phillies player",
    )
    @app_commands.describe(
        player="Player name (hitter or pitcher)",
        days="Comparison window vs. prior equal-length window",
    )
    @app_commands.choices(days=[
        app_commands.Choice(name="Last 7 days",  value=7),
        app_commands.Choice(name="Last 14 days", value=14),
        app_commands.Choice(name="Last 30 days", value=30),
    ])
    async def trends(
        self,
        interaction: discord.Interaction,
        player: str,
        days: int = 14,
    ) -> None:
        await interaction.response.defer()

        entry = self._resolve_player(player)
        if entry is None:
            await interaction.followup.send(
                f"❌ Could not find **{player}** on the Phillies 40-man roster.",
                ephemeral=True,
            )
            return

        player_id = entry["id"]
        player_name = entry["fullName"]
        is_pitcher = entry["is_pitcher"]
        player_type = "pitcher" if is_pitcher else "batter"

        win_start, win_end, prior_start, prior_end = self._date_windows(days)

        win_rows = fetch_statcast_for_range(player_id, player_type, win_start, win_end)
        prior_rows = fetch_statcast_for_range(player_id, player_type, prior_start, prior_end)

        il_note = f" _(IL — {entry['status_code']})_" if entry["on_il"] else ""
        window_label = f"Last {days} days  vs.  Prior {days} days"
        title = f"📊 {player_name}{il_note} — Trends"

        if is_pitcher:
            win_m = _compute_pitcher_metrics(win_rows)
            prior_m = _compute_pitcher_metrics(prior_rows)
            trend_list = _find_pitcher_trends(win_m, prior_m)
            format_fn = _pitcher_trend_line
        else:
            win_m = _compute_hitter_metrics(win_rows)
            prior_m = _compute_hitter_metrics(prior_rows)
            trend_list = _find_hitter_trends(win_m, prior_m)
            format_fn = _hitter_trend_line

        embed = discord.Embed(title=title, color=PHILLIES_RED)
        embed.set_footer(
            text=f"{window_label}  ·  Statcast via Baseball Savant  ·  Phillies Therapy Bot"
        )

        if not win_rows and not prior_rows:
            embed.description = "_No Statcast data found for this player in the selected windows._"
        elif not trend_list:
            win_n = win_m.get("pitches_seen" if not is_pitcher else "total_pitches", len(win_rows))
            prior_n = prior_m.get("pitches_seen" if not is_pitcher else "total_pitches", len(prior_rows))
            embed.description = (
                f"_No metrics crossed the significance threshold in this window._\n"
                f"Window: {win_n} {'pitches seen' if not is_pitcher else 'pitches thrown'}  |  "
                f"Prior: {prior_n} {'pitches seen' if not is_pitcher else 'pitches thrown'}"
            )
        else:
            lines = [format_fn(t) for t in trend_list]
            embed.description = "\n\n".join(lines)

        await interaction.followup.send(embed=embed)

    # ── Autocomplete ──────────────────────────────────────────────────────────

    @trends.autocomplete("player")
    async def player_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """All 40-man Phillies sorted A-Z by last name; IL players noted."""
        roster = self._roster()
        choices = []
        for p in roster:
            name = p["fullName"]
            display = f"{name} ({p['status_code']})" if p["on_il"] else name
            if current and current.lower() not in name.lower():
                continue
            choices.append(app_commands.Choice(name=display, value=name))
            if len(choices) == 25:
                break
        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrendsCog(bot))
