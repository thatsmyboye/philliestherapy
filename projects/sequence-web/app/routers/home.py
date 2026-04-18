from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        import statsapi
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        games = statsapi.schedule(date=today, sportId=1)
    except Exception:
        games = []

    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_nav": "home",
        "games": games,
    })


@router.get("/games/stream")
async def games_stream():
    from fastapi.responses import StreamingResponse
    from app.services.live import sse_generator

    async def gen():
        async for chunk in sse_generator("games"):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")
