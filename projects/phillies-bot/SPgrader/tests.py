"""
Tests for the PAR scoring engine.
Run: python -m pytest tests.py -v
"""

import sys
sys.path.insert(0, ".")

from scoring import (
    PitcherGameData, grade_pitcher,
    score_efficiency, score_run_prevention,
    score_strikeouts, score_walk_control,
    score_strike_ball_ratio, score_csw,
    score_batted_ball_quality,
)


def make_data(**kwargs) -> PitcherGameData:
    defaults = dict(
        name="Zack Wheeler",
        pitcher_id=554430,
        game_date="2025-04-01",
        opponent="NYM",
        home_away="home",
        outs_recorded=21,     # 7.0 IP
        hits=5, runs=2, earned_runs=2,
        walks=1, strikeouts=9,
        pitches_thrown=100, strikes_thrown=67,
        called_strikes=20, swinging_strikes=18,
        exit_velocities=[85.0, 90.0, 78.0, 88.0],
        launch_angles=[5.0, 25.0, -2.0, 10.0],
    )
    defaults.update(kwargs)
    return PitcherGameData(**defaults)


# ── Individual component tests ────────────────────────────────────────────────

def test_efficiency_complete_game():
    d = make_data(outs_recorded=27)
    assert score_efficiency(d) == 100.0

def test_efficiency_zero_outs():
    d = make_data(outs_recorded=0)
    assert score_efficiency(d) == 0.0

def test_efficiency_5_innings():
    d = make_data(outs_recorded=15)
    s = score_efficiency(d)
    assert 45 < s < 65, f"Expected ~55, got {s}"

def test_run_prevention_shutout():
    d = make_data(earned_runs=0, outs_recorded=21)
    assert score_run_prevention(d) == 100.0

def test_run_prevention_high_era():
    d = make_data(earned_runs=5, outs_recorded=12)  # 15.0 ERA equivalent
    s = score_run_prevention(d)
    assert s < 10, f"Expected near 0, got {s}"

def test_strikeouts_elite():
    d = make_data(strikeouts=14, outs_recorded=21)  # 18 K/9
    s = score_strikeouts(d)
    assert s >= 95

def test_strikeouts_poor():
    d = make_data(strikeouts=2, outs_recorded=21)   # ~2.6 K/9
    s = score_strikeouts(d)
    assert s < 25

def test_walk_control_no_walks():
    d = make_data(walks=0, outs_recorded=21)
    assert score_walk_control(d) == 100.0

def test_walk_control_high():
    d = make_data(walks=6, outs_recorded=15)   # ~14.4 BB/9
    s = score_walk_control(d)
    assert s < 5

def test_strike_pct_good():
    d = make_data(pitches_thrown=100, strikes_thrown=67)  # 67%
    s = score_strike_ball_ratio(d)
    assert s > 80

def test_csw_elite():
    d = make_data(pitches_thrown=100, called_strikes=18, swinging_strikes=20)  # 38%
    s = score_csw(d)
    assert s > 85

def test_batted_ball_no_data():
    d = make_data(exit_velocities=[], launch_angles=[])
    s = score_batted_ball_quality(d)
    assert s == 50.0

def test_batted_ball_soft_contact():
    d = make_data(exit_velocities=[70, 72, 68], launch_angles=[-5, 2, -3])  # soft grounders
    s = score_batted_ball_quality(d)
    assert s > 75

def test_batted_ball_hard_line_drives():
    d = make_data(exit_velocities=[105, 108, 103], launch_angles=[15, 18, 20])
    s = score_batted_ball_quality(d)
    assert s < 15

# ── Full grade tests ──────────────────────────────────────────────────────────

def test_grade_elite_outing():
    d = make_data(
        outs_recorded=27, earned_runs=0, strikeouts=12, walks=1,
        pitches_thrown=105, strikes_thrown=72,
        called_strikes=22, swinging_strikes=20,
        exit_velocities=[72, 75, 68], launch_angles=[2, -3, 5]
    )
    result = grade_pitcher(d)
    print(f"\nElite outing: {result.total_score} ({result.grade_letter})")
    assert result.total_score >= 85
    assert result.grade_letter in ("S", "A+", "A")

def test_grade_average_outing():
    d = make_data()  # defaults are a solid but not elite start
    result = grade_pitcher(d)
    print(f"\nAverage outing: {result.total_score} ({result.grade_letter})")
    assert 50 <= result.total_score <= 80

def test_grade_brutal_outing():
    d = make_data(
        outs_recorded=9, earned_runs=6, strikeouts=2, walks=4,
        pitches_thrown=70, strikes_thrown=38,
        called_strikes=8, swinging_strikes=5,
        exit_velocities=[100, 105, 98, 102], launch_angles=[18, 20, 15, 22]
    )
    result = grade_pitcher(d)
    print(f"\nBrutal outing: {result.total_score} ({result.grade_letter})")
    assert result.total_score < 35
    assert result.grade_letter in ("F", "D")

def test_grade_components_sum():
    """Weighted components should sum to total within rounding tolerance."""
    d = make_data()
    result = grade_pitcher(d)
    component_sum = sum(c.weighted for c in result.components)
    assert abs(component_sum - result.total_score) < 1.0, \
        f"Component sum {component_sum} vs total {result.total_score}"

def test_grade_weights_sum_100():
    from config import Config
    assert sum(Config.SCORE_WEIGHTS.values()) == 100


if __name__ == "__main__":
    # Quick sanity print
    d = make_data()
    r = grade_pitcher(d)
    print(f"\n{'='*60}")
    print(f"Wheeler sample: {r.total_score:.1f} PAR  |  {r.grade_letter} {r.grade_emoji}")
    print(f"{'='*60}")
    for c in r.components:
        print(f"  {c.name:<25} score={c.score:.1f}  weight={c.weight}%  weighted={c.weighted:.2f}")
    print(f"{'='*60}")
