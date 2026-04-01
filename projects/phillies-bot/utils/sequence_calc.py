"""
Pitch sequence analysis utilities, ported from sequencebaseball/pitch_viz.py.

Provides:
  - PITCH_TYPE_TO_NAME  fallback code → full name mapping
  - prepare_statcast_df  convert list[dict] rows from mlb_data into a DataFrame
  - analyze_pitch_sequences  identify most effective 2/3-pitch sequences
  - create_sequence_chart_bytes  render grouped bar chart → BytesIO PNG
"""
from __future__ import annotations

import io
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Headless backend — must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Pitch type abbreviation → full name fallback
# (Baseball Savant CSV includes pitch_name directly, but this covers gaps)
# ---------------------------------------------------------------------------
PITCH_TYPE_TO_NAME: dict[str, str] = {
    "FF": "4-Seam Fastball",
    "FA": "Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "ST": "Sweeper",
    "CU": "Curveball",
    "KC": "Knuckle-Curve",
    "CH": "Changeup",
    "FS": "Splitter",
    "FO": "Forkball",
    "SV": "Slurve",
    "CS": "Slow Curve",
    "KN": "Knuckleball",
    "EP": "Eephus",
    "SC": "Screwball",
    "PH": "Pitchout",
}


def prepare_statcast_df(rows: list[dict]) -> pd.DataFrame:
    """
    Convert the list[dict] returned by get_pitcher_statcast() into a DataFrame
    suitable for analyze_pitch_sequences().

    - Uses pitch_name column if present and non-empty; otherwise maps pitch_type
      through PITCH_TYPE_TO_NAME.
    - Coerces numeric columns needed by the sequence analysis.
    """
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Ensure pitch_name column exists and is populated
    if "pitch_name" not in df.columns or df["pitch_name"].replace("", pd.NA).isna().all():
        df["pitch_name"] = df.get("pitch_type", pd.Series(dtype=str)).map(
            PITCH_TYPE_TO_NAME
        )
    else:
        # Fill any blanks using the fallback mapping
        mask = df["pitch_name"].replace("", pd.NA).isna()
        df.loc[mask, "pitch_name"] = df.loc[mask, "pitch_type"].map(PITCH_TYPE_TO_NAME)

    # Coerce numeric columns
    for col in ("at_bat_number", "pitch_number", "zone", "plate_x", "plate_z"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Sequence analysis — ported verbatim from sequencebaseball/pitch_viz.py
# ---------------------------------------------------------------------------

def analyze_pitch_sequences(
    df: pd.DataFrame,
    pitcher_name: str,
    min_sample_size: int = 20,
    success_metric: str = "overall",
    batter_hand: Optional[str] = None,
    sequence_length: int = 2,
    sequence_position: str = "any",
) -> pd.DataFrame:
    """
    Analyze and identify the most effective pitch sequences for a pitcher.

    Parameters
    ----------
    df : pd.DataFrame
        Statcast pitch data (output of prepare_statcast_df).
    pitcher_name : str
        Pitcher's name (used for logging only).
    min_sample_size : int
        Minimum occurrences required for a sequence to be included (default 20).
    success_metric : str
        Column to sort by: 'overall', 'whiff_rate', 'chase_rate', 'weak_contact'.
    batter_hand : str | None
        'R' or 'L' to filter by batter handedness; None = all batters.
    sequence_length : int
        Number of pitches per sequence (2 or 3).
    sequence_position : str
        'any'   — all consecutive sequences within a PA
        'start' — only the first N pitches of each PA
        'end'   — only the last N pitches of each PA

    Returns
    -------
    pd.DataFrame with columns:
        Sequence, Usage, Whiff Rate, Chase Rate, Weak Contact Rate, Overall Score
    Sorted descending by success_metric.  Empty DataFrame if no qualifying sequences.
    """
    required_cols = ["pitch_name", "game_date", "at_bat_number", "pitch_number", "description"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        return pd.DataFrame()

    filtered_df = df.copy()
    if batter_hand and "stand" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["stand"] == batter_hand]

    filtered_df["at_bat_id"] = (
        filtered_df["game_date"].astype(str) + "_" +
        filtered_df["at_bat_number"].astype(str)
    )
    filtered_df = filtered_df.sort_values(["at_bat_id", "pitch_number"])

    sequences = []

    for _ab_id, ab_group in filtered_df.groupby("at_bat_id"):
        ab_group = ab_group.sort_values("pitch_number")
        pitches = ab_group["pitch_name"].values
        num_pitches = len(pitches)

        if sequence_position in ("start", "end") and num_pitches < 2:
            continue

        if sequence_position == "start":
            indices = [0] if num_pitches >= sequence_length else []
        elif sequence_position == "end":
            indices = [num_pitches - sequence_length] if num_pitches >= sequence_length else []
        else:
            indices = range(num_pitches - sequence_length + 1)

        for i in indices:
            sequence_raw = pitches[i : i + sequence_length]
            sequence = tuple(str(p) for p in sequence_raw if pd.notna(p))

            if len(sequence) != sequence_length:
                continue

            final_pitch = ab_group.iloc[i + sequence_length - 1]

            # Zone determination
            if "zone" in final_pitch.index and pd.notna(final_pitch["zone"]):
                try:
                    in_zone = float(final_pitch["zone"]) <= 9
                except (ValueError, TypeError):
                    in_zone = True
            elif "plate_x" in final_pitch.index and "plate_z" in final_pitch.index:
                px, pz = final_pitch["plate_x"], final_pitch["plate_z"]
                try:
                    in_zone = abs(float(px)) <= 0.83 and 1.5 <= float(pz) <= 3.5
                except (ValueError, TypeError):
                    in_zone = True
            else:
                in_zone = True

            swing = final_pitch["description"] in (
                "swinging_strike", "foul", "foul_tip",
                "hit_into_play", "swinging_strike_blocked",
            )
            whiff = final_pitch["description"] == "swinging_strike"
            chase = (not in_zone) and swing

            weak_contact = False
            if final_pitch["description"] == "hit_into_play":
                if "events" in final_pitch.index and pd.notna(final_pitch["events"]):
                    weak_contact = final_pitch["events"] in (
                        "field_out", "force_out", "grounded_into_double_play",
                        "double_play", "sac_fly", "fielders_choice",
                    )
                else:
                    weak_contact = True

            sequences.append({
                "sequence_str": " → ".join(sequence),
                "swing": swing,
                "whiff": whiff,
                "in_zone": in_zone,
                "chase": chase,
                "weak_contact": weak_contact,
            })

    if not sequences:
        return pd.DataFrame()

    seq_df = pd.DataFrame(sequences)

    results = []
    for seq_name, grp in seq_df.groupby("sequence_str"):
        if len(grp) < min_sample_size:
            continue

        total = len(grp)
        swings = grp["swing"].sum()
        whiffs = grp["whiff"].sum()
        outside_zone = (~grp["in_zone"]).sum()
        chases = grp["chase"].sum()
        weak_contacts = grp["weak_contact"].sum()

        whiff_rate = (whiffs / swings * 100) if swings > 0 else 0.0
        chase_rate = (chases / outside_zone * 100) if outside_zone > 0 else 0.0
        weak_contact_rate = weak_contacts / total * 100
        overall_score = whiff_rate * 0.5 + chase_rate * 0.3 + weak_contact_rate * 0.2

        results.append({
            "Sequence": seq_name,
            "Usage": total,
            "Whiff Rate": round(whiff_rate, 1),
            "Chase Rate": round(chase_rate, 1),
            "Weak Contact Rate": round(weak_contact_rate, 1),
            "Overall Score": round(overall_score, 1),
        })

    if not results:
        return pd.DataFrame()

    results_df = pd.DataFrame(results)

    sort_col = {
        "whiff_rate": "Whiff Rate",
        "chase_rate": "Chase Rate",
        "weak_contact": "Weak Contact Rate",
        "overall": "Overall Score",
    }.get(success_metric, "Overall Score")

    return results_df.sort_values(sort_col, ascending=False)


# ---------------------------------------------------------------------------
# Chart generation — adapted from sequencebaseball/pitch_viz.py
# Returns BytesIO instead of saving to a file path.
# ---------------------------------------------------------------------------

def create_sequence_chart_bytes(
    sequence_df: pd.DataFrame,
    pitcher_name: str,
    batter_hand: Optional[str] = None,
    top_n: int = 8,
) -> io.BytesIO:
    """
    Render a grouped bar chart of the top N pitch sequences and return it as
    a PNG-encoded BytesIO buffer suitable for discord.File.

    Bars show Whiff Rate, Chase Rate, and Weak Contact Rate side-by-side for
    each sequence.  Usage (n=X) is annotated above each group.
    """
    plot_df = sequence_df.head(top_n).copy().reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 7), dpi=130)
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    x = np.arange(len(plot_df))
    width = 0.25

    bars_whiff = ax.bar(
        x - width, plot_df["Whiff Rate"], width,
        label="Whiff Rate", color="#E63946", alpha=0.9,
    )
    bars_chase = ax.bar(
        x, plot_df["Chase Rate"], width,
        label="Chase Rate", color="#FFD166", alpha=0.9,
    )
    bars_weak = ax.bar(
        x + width, plot_df["Weak Contact Rate"], width,
        label="Weak Contact Rate", color="#06AED5", alpha=0.9,
    )

    hand_text = (
        " vs RHH" if batter_hand == "R"
        else " vs LHH" if batter_hand == "L"
        else " vs All Batters"
    )
    ax.set_title(
        f"{pitcher_name} — Top Pitch Sequences{hand_text}",
        fontsize=15, fontweight="bold", color="white", pad=14,
    )
    ax.set_xlabel("Pitch Sequence", fontsize=11, color="#cccccc", labelpad=8)
    ax.set_ylabel("Rate (%)", fontsize=11, color="#cccccc")
    ax.set_xticks(x)
    ax.set_xticklabels(
        plot_df["Sequence"], rotation=40, ha="right",
        fontsize=9, color="white",
    )
    ax.tick_params(axis="y", colors="#cccccc")
    ax.spines[:].set_color("#444466")
    ax.grid(axis="y", alpha=0.25, color="#555577")

    max_rate = plot_df[["Whiff Rate", "Chase Rate", "Weak Contact Rate"]].max().max()
    ax.set_ylim(0, max(max_rate * 1.18, 5))

    legend = ax.legend(loc="upper right", fontsize=9, framealpha=0.3)
    for text in legend.get_texts():
        text.set_color("white")

    # Usage annotations above each bar group
    for i, row in plot_df.iterrows():
        ax.text(
            i, max_rate * 1.07, f"n={row['Usage']}",
            ha="center", va="bottom", fontsize=8,
            color="#aaaacc", style="italic",
        )

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf
