import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.services.live import sse_generator

log = logging.getLogger("steal")

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")

MIN_ATTEMPTS = 2


def _load_steal_leaderboard() -> list[dict]:
    """Load steal grades from the bot's persistent state JSON."""
    import utils.state as state_store
    state = state_store.load()
    grades = state_store.get_steal_grades(state)

    rows = []
    for pid_str, entry in grades.items():
        attempts = entry.get("attempts", [])
        if len(attempts) < MIN_ATTEMPTS:
            continue
        sb = sum(1 for a in attempts if a["success"])
        cs = len(attempts) - sb
        total_weight = sum(a["difficulty"] for a in attempts)
        weighted_success = sum(a["difficulty"] for a in attempts if a["success"])
        wsr = (weighted_success / total_weight * 100) if total_weight > 0 else 0.0
        avg_diff = total_weight / len(attempts)
        rows.append({
            "name": entry["name"],
            "sb": sb,
            "cs": cs,
            "wsr": round(wsr, 1),
            "avg_diff": round(avg_diff, 2),
            "attempts": len(attempts),
        })

    rows.sort(key=lambda r: r["wsr"], reverse=True)
    return rows


@router.get("/steal/", response_class=HTMLResponse)
async def steal_leaderboard(request: Request):
    try:
        rows = _load_steal_leaderboard()
        error = None
    except Exception:
        log.error("Steal leaderboard load failed", exc_info=True)
        rows = []
        error = "Leaderboard data temporarily unavailable."

    return templates.TemplateResponse(request, "steal/index.html", {
        "active_nav": "steal",
        "rows": rows,
        "error": error,
    })


@router.get("/steal/live", response_class=HTMLResponse)
async def steal_live(request: Request):
    return templates.TemplateResponse(request, "steal/live.html", {
        "active_nav": "live-steal",
    })


@router.get("/steal/stream")
async def steal_stream():
    async def gen():
        async for chunk in sse_generator("steal"):
            yield chunk
    return StreamingResponse(gen(), media_type="text/event-stream")
