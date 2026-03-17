"""
Philly Ace Rating (PAR) — proprietary SP grading model for Phillies Therapy.

Scale: 0–100
Each component is scored 0–100 then weighted per Config.SCORE_WEIGHTS.

Components
──────────
1. Efficiency (22%)      — Outs recorded vs. outs possible (max 27 for a CG)
2. Run Prevention (24%)  — Earned runs scaled to a 9-IP ERA baseline
3. Strikeout Rate (14%)  — K per 9 IP, normalized
4. Walk Control (14%)    — BB per 9 IP, normalized (inverted)
5. Strike/Ball Ratio (10%) — Overall strike% of total pitches
6. CSW% (8%)             — Called + Swinging Strikes / Total Pitches
7. Batted Ball Quality (8%) — Composite of exit velo + launch angle (inverted)
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Optional
from config import Config

log = logging.getLogger("scoring")


# ─── Input Data Class ─────────────────────────────────────────────────────────

@dataclass
class PitcherGameData:
    name: str
    pitcher_id: int
    game_date: str
    opponent: str
    home_away: str                  # "home" | "away"

    # Standard boxscore stats
    outs_recorded: int = 0          # e.g. 15 = 5.0 IP
    hits: int = 0
    runs: int = 0
    earned_runs: int = 0
    walks: int = 0
    strikeouts: int = 0
    home_runs: int = 0
    batters_faced: int = 0
    pitches_thrown: int = 0
    strikes_thrown: int = 0

    # Statcast pitch-level (populated from Savant)
    called_strikes: int = 0
    swinging_strikes: int = 0
    exit_velocities: list[float] = field(default_factory=list)  # BIP only
    launch_angles: list[float] = field(default_factory=list)    # BIP only

    # Computed
    @property
    def innings_pitched(self) -> float:
        full = self.outs_recorded // 3
        partial = self.outs_recorded % 3
        return full + partial / 3

    @property
    def innings_pitched_display(self) -> str:
        full = self.outs_recorded // 3
        partial = self.outs_recorded % 3
        return f"{full}.{partial}" if partial else str(full)

    @property
    def strike_pct(self) -> float:
        if self.pitches_thrown == 0:
            return 0.0
        return self.strikes_thrown / self.pitches_thrown

    @property
    def csw_pct(self) -> float:
        if self.pitches_thrown == 0:
            return 0.0
        return (self.called_strikes + self.swinging_strikes) / self.pitches_thrown

    @property
    def k_per_9(self) -> float:
        if self.innings_pitched == 0:
            return 0.0
        return (self.strikeouts / self.innings_pitched) * 9

    @property
    def bb_per_9(self) -> float:
        if self.innings_pitched == 0:
            return 0.0
        return (self.walks / self.innings_pitched) * 9

    @property
    def avg_exit_velocity(self) -> Optional[float]:
        if not self.exit_velocities:
            return None
        return sum(self.exit_velocities) / len(self.exit_velocities)

    @property
    def avg_launch_angle(self) -> Optional[float]:
        if not self.launch_angles:
            return None
        return sum(self.launch_angles) / len(self.launch_angles)


# ─── Scoring Engine ────────────────────────────────────────────────────────────

@dataclass
class ComponentScore:
    name: str
    raw_value: float
    score: float        # 0–100
    weight: int
    weighted: float     # score * weight / 100


@dataclass
class PARResult:
    pitcher_name: str
    pitcher_id: int
    game_date: str
    opponent: str
    total_score: float          # 0–100, rounded to 1 decimal
    grade_letter: str
    grade_emoji: str
    components: list[ComponentScore]
    data: PitcherGameData


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def score_efficiency(data: PitcherGameData) -> float:
    """
    Rewards deep outings. Full 27 outs = 100.
    Uses a curve: 15 outs (5 IP) ≈ 55, 21 outs (7 IP) ≈ 82, 27 outs = 100.
    Penalizes heavily for fewer than 9 outs (3 IP).
    """
    o = data.outs_recorded
    # Sigmoid-like curve anchored at 0 and 27
    if o == 0:
        return 0.0
    # base linear component
    linear = (o / 27) * 85
    # bonus for longevity (bonus tops out at 15 for a complete game)
    bonus = min(15, (o / 27) ** 1.6 * 15)
    return _clamp(linear + bonus)


def score_run_prevention(data: PitcherGameData) -> float:
    """
    ERA-based. Converts to per-9 then maps:
      0.00 ERA → 100
      2.00 ERA → 85
      3.50 ERA → 70  (roughly league avg)
      5.00 ERA → 50
      7.00 ERA → 25
      9.00+    → 0
    """
    if data.innings_pitched == 0:
        return 0.0
    era = (data.earned_runs / data.innings_pitched) * 9
    # Exponential decay from 100
    score = 100 * math.exp(-0.22 * era)
    return _clamp(score)


def score_strikeouts(data: PitcherGameData) -> float:
    """
    K/9 normalized. Elite ~13+, avg ~8.5, poor <5.
      K/9  0  → 0
      K/9  5  → 30
      K/9  9  → 65
      K/9 12  → 85
      K/9 15+ → 100
    """
    k9 = data.k_per_9
    score = _clamp((k9 / 15) * 100, 0, 100)
    # Soften lower bound — even 5 K/9 deserves some credit
    score = score ** 0.85 * (100 ** 0.15)
    return _clamp(score)


def score_walk_control(data: PitcherGameData) -> float:
    """
    BB/9 inverted.
      BB/9  0.0 → 100
      BB/9  2.0 → 80
      BB/9  3.5 → 55  (league avg)
      BB/9  5.0 → 30
      BB/9  7+  → 0
    """
    bb9 = data.bb_per_9
    score = 100 * math.exp(-0.28 * bb9)
    return _clamp(score)


def score_strike_ball_ratio(data: PitcherGameData) -> float:
    """
    Strike% of all pitches.
      <50%  → approaching 0
       60%  → 50
       65%  → 75 (MLB avg ≈ 62–64%)
       70%+ → 100
    """
    sp = data.strike_pct * 100  # convert to percentage
    if sp <= 40:
        return 0.0
    score = ((sp - 40) / 30) * 100   # 40% → 0, 70% → 100
    return _clamp(score)


def score_csw(data: PitcherGameData) -> float:
    """
    CSW% (Called Strikes + Whiffs / Total Pitches).
      <20%  → 0
       28%  → 50 (MLB avg ≈ 27–28%)
       35%  → 85
       40%+ → 100
    """
    csw = data.csw_pct * 100
    if csw <= 18:
        return 0.0
    score = ((csw - 18) / 22) * 100  # 18% → 0, 40% → 100
    return _clamp(score)


def score_batted_ball_quality(data: PitcherGameData) -> float:
    """
    Lower exit velo + ideal (either very low or very high) launch angle = good.
    We care about hard contact on line-drive trajectories being BAD.

    BBQ Composite (0–100, higher = better for pitcher):
      EV component: 100 - (avg_ev - 75) * 2.5  (75 mph = best case, 105 = worst)
      LA component: sweet spot damage = LDs (10–25°) are worst.
                    We penalize LA in [10, 25] and reward anything < 5 or > 35.

    If no BIP data, fall back to neutral (50).
    """
    if not data.exit_velocities:
        return 50.0  # neutral when no Statcast data

    avg_ev = data.avg_exit_velocity
    avg_la = data.avg_launch_angle

    # EV score: 75 mph → 100, 105 mph → 0
    ev_score = _clamp(100 - (avg_ev - 75) * (100 / 30))

    # LA score: penalize line-drive zone (10–25°)
    # Ground balls (<10°) and pop-ups (>30°) are good for pitchers
    # Hard line drives (10–25°) are the worst
    if avg_la is None:
        la_score = 50.0
    elif avg_la < 10:
        la_score = 80.0   # ground balls — good
    elif avg_la < 25:
        # LD zone — worst, linearly penalize
        fraction = (avg_la - 10) / 15  # 0 at 10°, 1 at 25°
        la_score = 80 - fraction * 60   # 80 → 20
    elif avg_la < 35:
        # Fly ball zone — medium
        la_score = 60.0
    else:
        # Pop-up zone — great for pitcher
        la_score = 90.0

    return _clamp(ev_score * 0.65 + la_score * 0.35)


# ─── Main Grader ──────────────────────────────────────────────────────────────

def grade_pitcher(data: PitcherGameData) -> PARResult:
    """
    Compute the Philly Ace Rating for a SP outing.
    Returns a PARResult with per-component breakdown and overall score.
    """
    weights = Config.SCORE_WEIGHTS

    scorers = [
        ("efficiency",          score_efficiency,         weights["efficiency"]),
        ("run_prevention",      score_run_prevention,     weights["run_prevention"]),
        ("strikeouts",          score_strikeouts,         weights["strikeouts"]),
        ("walk_control",        score_walk_control,       weights["walk_control"]),
        ("strike_ball_ratio",   score_strike_ball_ratio,  weights["strike_ball_ratio"]),
        ("csw",                 score_csw,                weights["csw"]),
        ("batted_ball_quality", score_batted_ball_quality,weights["batted_ball_quality"]),
    ]

    components = []
    total_weighted = 0.0

    for name, fn, weight in scorers:
        raw = fn(data)
        weighted = raw * weight / 100
        total_weighted += weighted
        components.append(ComponentScore(
            name=name,
            raw_value=_get_display_raw(name, data),
            score=round(raw, 1),
            weight=weight,
            weighted=round(weighted, 2),
        ))

    total = round(total_weighted, 1)

    # Grade label
    grade_letter, grade_emoji = "F", "💀"
    for (lo, hi), (letter, emoji) in Config.GRADE_LABELS.items():
        if lo <= total < hi:
            grade_letter = letter
            grade_emoji = emoji
            break
    if total == 100:
        grade_letter, grade_emoji = "S", "🏆"

    log.info(
        f"PAR scored: {data.name} | {data.game_date} | "
        f"score={total} grade={grade_letter}"
    )

    return PARResult(
        pitcher_name=data.name,
        pitcher_id=data.pitcher_id,
        game_date=data.game_date,
        opponent=data.opponent,
        total_score=total,
        grade_letter=grade_letter,
        grade_emoji=grade_emoji,
        components=components,
        data=data,
    )


def _get_display_raw(name: str, d: PitcherGameData) -> float:
    """Return the human-readable raw value for each component."""
    return {
        "efficiency":          round(d.innings_pitched, 1),
        "run_prevention":      d.earned_runs,
        "strikeouts":          d.strikeouts,
        "walk_control":        d.walks,
        "strike_ball_ratio":   round(d.strike_pct * 100, 1),
        "csw":                 round(d.csw_pct * 100, 1),
        "batted_ball_quality": round(d.avg_exit_velocity or 0, 1),
    }.get(name, 0.0)
