from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/luck/", response_class=HTMLResponse)
async def luck_index(request: Request, team_id: int = 143, lucky: int = 1):
    from utils.mlb_data import get_all_mlb_teams, get_team_luck, get_team_abbreviations

    teams = get_all_mlb_teams()
    abbr_map = get_team_abbreviations()
    team_abbr = abbr_map.get(team_id, "PHI")

    error = None
    data = {"hitters": [], "pitchers": []}
    try:
        data = get_team_luck(team_abbr, team_id, bool(lucky))
    except Exception as exc:
        error = str(exc)

    team_name = next((t["name"] for t in teams if t["id"] == team_id), f"Team {team_id}")

    return templates.TemplateResponse(request, "luck/index.html", {
        "active_nav": "luck",
        "teams": teams,
        "selected_team_id": team_id,
        "lucky": bool(lucky),
        "hitters": data["hitters"],
        "pitchers": data["pitchers"],
        "team_name": team_name,
        "error": error,
    })
