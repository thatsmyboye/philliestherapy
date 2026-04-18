from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/getaway/", response_class=HTMLResponse)
async def getaway_index(request: Request):
    return templates.TemplateResponse("getaway/index.html", {
        "request": request,
        "active_nav": "getaway",
        "result": None,
        "error": None,
        "pitcher_name": "",
    })


@router.post("/getaway/", response_class=HTMLResponse)
async def getaway_search(
    request: Request,
    pitcher_name: str = Form(...),
):
    from utils.player_lookup import resolve_player
    from utils.mlb_data import get_pitcher_statcast, PITCH_TYPE_LABELS
    from cogs.getaway import _analyze_getaway, _grade

    error = None
    result = None

    try:
        player_id, resolved_name, lookup_err = resolve_player(pitcher_name, require_pitcher=True)
        if player_id is None:
            raise ValueError(lookup_err or f"Could not find pitcher '{pitcher_name}'")

        rows = get_pitcher_statcast(player_id)
        if not rows:
            raise ValueError(f"No Statcast data found for {resolved_name} this season.")

        analysis = _analyze_getaway(rows)

        # Enrich by_type with labels
        by_type_display = []
        for pt, data in analysis.get("by_type", {}).items():
            rate = data["escaped"] / data["total"] * 100 if data["total"] > 0 else 0
            by_type_display.append({
                "label": PITCH_TYPE_LABELS.get(pt, pt),
                "code": pt,
                "total": data["total"],
                "escaped": data["escaped"],
                "rate": rate,
                "runs": data["runs"],
            })
        by_type_display.sort(key=lambda x: x["total"], reverse=True)

        result = {
            "pitcher_name": resolved_name,
            "pitcher_id": player_id,
            "total_terrible": analysis["total_terrible"],
            "total_escaped": analysis["total_escaped"],
            "escape_rate": analysis["escape_rate"],
            "runs_stolen": analysis["runs_stolen"],
            "grade_letter": analysis["grade"][0],
            "grade_label": analysis["grade"][1],
            "grade_css": "Ap" if analysis["grade"][0] == "A+" else analysis["grade"][0][:1],
            "top_escapes": analysis["top_escapes"],
            "by_type": by_type_display,
            "low_sample": analysis["low_sample"],
        }
    except Exception as exc:
        error = str(exc)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("getaway/_results.html", {
            "request": request,
            "result": result,
            "error": error,
        })

    return templates.TemplateResponse("getaway/index.html", {
        "request": request,
        "active_nav": "getaway",
        "result": result,
        "error": error,
        "pitcher_name": pitcher_name,
    })
