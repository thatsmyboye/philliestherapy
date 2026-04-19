import sys
import os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.services.live import sse_generator, broadcast

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")

# Lazy-load the leaderboard so imports resolve after sys.path is set in main.py
_leaderboard = None


def _lb():
    global _leaderboard
    if _leaderboard is None:
        from cogs.spgrader.leaderboard import Leaderboard
        _leaderboard = Leaderboard()
    return _leaderboard


def _grade_css(grade: str) -> str:
    """Map grade letter to CSS class suffix."""
    return "Ap" if grade == "A+" else (grade[:1] if grade else "")


@router.get("/par/", response_class=HTMLResponse)
async def par_leaderboard(request: Request, n: int = 25):
    lb = _lb()
    season_leaders = lb.top_averages(n=n, min_games=1)
    top_games = lb.top_individual(n=10)

    # Enrich with grade CSS class
    for entry in season_leaders:
        entry["grade_css"] = _grade_css(entry.get("grade", ""))
    top_games_dicts = []
    for r in top_games:
        d = {
            "pitcher_name": r.pitcher_name,
            "pitcher_id": r.pitcher_id,
            "game_date": r.game_date,
            "opponent": r.opponent,
            "score": r.score,
            "grade": r.grade,
            "grade_css": _grade_css(r.grade),
            "ip": r.ip,
            "k": r.k,
            "bb": r.bb,
            "er": r.er,
            "h": r.h,
        }
        top_games_dicts.append(d)

    return templates.TemplateResponse(request, "par/leaderboard.html", {
        "active_nav": "par",
        "season_leaders": season_leaders,
        "top_games": top_games_dicts,
    })


@router.get("/par/live", response_class=HTMLResponse)
async def par_live(request: Request):
    return templates.TemplateResponse(request, "par/live.html", {
        "active_nav": "live-par",
    })


@router.get("/par/stream")
async def par_stream():
    """SSE endpoint — streams live PAR grade events to the browser."""
    async def event_gen():
        async for chunk in sse_generator("par"):
            yield chunk

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/par/{pitcher_id}", response_class=HTMLResponse)
async def par_player(request: Request, pitcher_id: int):
    lb = _lb()
    all_records = [
        r for r in lb._records
        if r.pitcher_id == pitcher_id and not r.is_spring_training
    ]
    all_records.sort(key=lambda r: r.game_date, reverse=True)

    if not all_records:
        return templates.TemplateResponse(request, "par/player.html", {
            "active_nav": "par",
            "pitcher_name": f"Pitcher #{pitcher_id}",
            "games": [],
            "avg": None,
            "rank": None,
        })

    pitcher_name = all_records[0].pitcher_name
    avg = lb.get_pitcher_average(pitcher_id)
    rank = lb.pitcher_rank(pitcher_id)

    games = []
    for r in all_records:
        games.append({
            "game_date": r.game_date,
            "opponent": r.opponent,
            "score": r.score,
            "grade": r.grade,
            "grade_css": _grade_css(r.grade),
            "ip": r.ip,
            "k": r.k,
            "bb": r.bb,
            "er": r.er,
            "h": r.h,
        })

    return templates.TemplateResponse(request, "par/player.html", {
        "active_nav": "par",
        "pitcher_name": pitcher_name,
        "pitcher_id": pitcher_id,
        "games": games,
        "avg": avg,
        "rank": rank,
    })
