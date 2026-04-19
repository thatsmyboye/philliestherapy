from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/matchup/", response_class=HTMLResponse)
async def matchup_index(request: Request, team_id: int = 143):
    from utils.mlb_data import get_all_mlb_teams, get_next_game_with_probables_for_team

    teams = get_all_mlb_teams()
    game = get_next_game_with_probables_for_team(team_id)

    pitcher_data = {}
    if game:
        for role, probable in [
            ("team", game.get("team_probable")),
            ("opp", game.get("opp_probable")),
        ]:
            if probable:
                pitcher_data[role] = _build_pitcher_profile(probable["id"], probable["fullName"])

    return templates.TemplateResponse(request, "matchup/index.html", {
        "active_nav": "matchup",
        "teams": teams,
        "selected_team_id": team_id,
        "game": game,
        "pitcher_data": pitcher_data,
        "error": None,
    })


def _build_pitcher_profile(pitcher_id: int, pitcher_name: str) -> dict:
    from utils.mlb_data import (
        get_pitcher_statcast, get_pitcher_statcast_multiyear,
        PITCH_TYPE_LABELS, _to_float, is_early_regular_season,
    )
    from collections import defaultdict

    rows = get_pitcher_statcast(pitcher_id)
    if not rows and is_early_regular_season():
        rows = get_pitcher_statcast_multiyear(pitcher_id)

    if not rows:
        return {"name": pitcher_name, "arsenal": [], "total_pitches": 0}

    by_type: dict[str, list] = defaultdict(list)
    for row in rows:
        pt = row.get("pitch_type", "").strip()
        if pt:
            by_type[pt].append(row)

    total = sum(len(v) for v in by_type.values())

    arsenal = []
    for pt, pt_rows in sorted(by_type.items(), key=lambda x: len(x[1]), reverse=True)[:6]:
        n = len(pt_rows)
        velos = [_to_float(r.get("release_speed")) for r in pt_rows]
        velos = [v for v in velos if v]
        swings = sum(
            1 for r in pt_rows
            if r.get("description", "") in ("swinging_strike", "swinging_strike_blocked", "foul_tip")
        )
        pfx_xs = [_to_float(r.get("pfx_x")) for r in pt_rows]
        pfx_zs = [_to_float(r.get("pfx_z")) for r in pt_rows]
        pfx_xs = [v * 12 for v in pfx_xs if v is not None]
        pfx_zs = [v * 12 for v in pfx_zs if v is not None]

        arsenal.append({
            "code": pt,
            "label": PITCH_TYPE_LABELS.get(pt, pt),
            "usage_pct": n / total * 100 if total else 0,
            "avg_velo": sum(velos) / len(velos) if velos else None,
            "whiff_pct": swings / n * 100,
            "h_break": sum(pfx_xs) / len(pfx_xs) if pfx_xs else None,
            "v_break": sum(pfx_zs) / len(pfx_zs) if pfx_zs else None,
            "n": n,
        })

    return {
        "name": pitcher_name,
        "pitcher_id": pitcher_id,
        "arsenal": arsenal,
        "total_pitches": total,
    }
