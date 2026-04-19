from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


def _date_windows(days: int) -> tuple[str, str, str, str]:
    today = date.today()
    win_start = (today - timedelta(days=days)).isoformat()
    win_end = today.isoformat()
    prior_start = (today - timedelta(days=2 * days)).isoformat()
    prior_end = (today - timedelta(days=days + 1)).isoformat()
    return win_start, win_end, prior_start, prior_end


def _delta_css(delta: float, up_is_bad) -> str:
    if up_is_bad is None:
        return "delta-neu"
    going_up = delta > 0
    good = not going_up if up_is_bad else going_up
    return "delta-pos" if good else "delta-neg"


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


@router.get("/trends/", response_class=HTMLResponse)
async def trends_index(request: Request):
    return templates.TemplateResponse(request, "trends/index.html", {
        "active_nav": "trends",
        "result": None,
        "error": None,
        "player_name": "",
        "days": 14,
    })


@router.post("/trends/", response_class=HTMLResponse)
async def trends_search(
    request: Request,
    player_name: str = Form(...),
    days: int = Form(14),
):
    from utils.player_lookup import resolve_player
    from utils.mlb_data import fetch_statcast_for_range, PITCH_TYPE_LABELS
    from cogs.trends import (
        _compute_hitter_metrics, _compute_pitcher_metrics,
        _find_hitter_trends, _find_pitcher_trends,
        _HITTER_META, _PITCHER_META,
    )

    error = None
    result = None

    try:
        # Try pitcher first, fall back to hitter, then generic
        player_id, resolved_name, _ = resolve_player(player_name, require_pitcher=True)
        is_pitcher = player_id is not None
        if player_id is None:
            player_id, resolved_name, _ = resolve_player(player_name, require_hitter=True)
        if player_id is None:
            player_id, resolved_name, lookup_err = resolve_player(player_name)
        if player_id is None:
            raise ValueError(lookup_err or f"Could not find player '{player_name}'")
        player_type = "pitcher" if is_pitcher else "batter"

        win_start, win_end, prior_start, prior_end = _date_windows(days)

        win_rows = fetch_statcast_for_range(player_id, player_type, win_start, win_end)
        prior_rows = fetch_statcast_for_range(player_id, player_type, prior_start, prior_end)

        if not win_rows and not prior_rows:
            raise ValueError(f"No Statcast data for {resolved_name} in the last {days * 2} days.")

        if is_pitcher:
            win_m = _compute_pitcher_metrics(win_rows)
            prior_m = _compute_pitcher_metrics(prior_rows)
            raw_trends = _find_pitcher_trends(win_m, prior_m)
            trends_display = []
            for t in raw_trends:
                pt_label = PITCH_TYPE_LABELS.get(t["pitch_type"], t["pitch_type"])
                label, unit, up_is_bad = _PITCHER_META[t["key"]]
                sign = "+" if t["delta"] > 0 else ""
                delta_str = (f"{sign}{t['delta']:.0f}{unit}" if unit == "rpm"
                             else f"{sign}{t['delta']:.1f}{unit}")
                trends_display.append({
                    "title": f"{pt_label} — {label}",
                    "delta_str": delta_str,
                    "delta_css": _delta_css(t["delta"], up_is_bad),
                    "window_val": _fmt_val(t["window_val"], unit),
                    "prior_val": _fmt_val(t["prior_val"], unit),
                    "n": t["n"],
                    "n_label": "pitches",
                })
            sample_n = win_m.get("total_pitches", len(win_rows))
        else:
            win_m = _compute_hitter_metrics(win_rows)
            prior_m = _compute_hitter_metrics(prior_rows)
            raw_trends = _find_hitter_trends(win_m, prior_m)
            trends_display = []
            for t in raw_trends:
                label, unit, up_is_bad = _HITTER_META[t["key"]]
                sign = "+" if t["delta"] > 0 else ""
                delta_str = (f"{sign}{t['delta']:.3f}" if unit == ""
                             else f"{sign}{t['delta']:.1f}{unit}")
                trends_display.append({
                    "title": label,
                    "delta_str": delta_str,
                    "delta_css": _delta_css(t["delta"], up_is_bad),
                    "window_val": _fmt_val(t["window_val"], unit),
                    "prior_val": _fmt_val(t["prior_val"], unit),
                    "n": t["n"],
                    "n_label": "pitches seen" if t["key"] == "whiff_rate" else "batted balls",
                })
            sample_n = win_m.get("pitches_seen", len(win_rows))

        result = {
            "player_name": resolved_name,
            "is_pitcher": is_pitcher,
            "days": days,
            "trends": trends_display,
            "sample_n": sample_n,
            "win_start": win_start,
            "win_end": win_end,
            "prior_start": prior_start,
            "prior_end": prior_end,
        }
    except Exception as exc:
        error = str(exc)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "trends/_results.html", {
            "result": result,
            "error": error,
        })

    return templates.TemplateResponse(request, "trends/index.html", {
        "active_nav": "trends",
        "result": result,
        "error": error,
        "player_name": player_name,
        "days": days,
    })
