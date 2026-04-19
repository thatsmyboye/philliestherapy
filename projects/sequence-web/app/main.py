import sys
import os
from pathlib import Path

# Make bot utilities importable
BOT_ROOT = Path(__file__).resolve().parents[2] / "phillies-bot"
sys.path.insert(0, str(BOT_ROOT))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers import home, par, sequence, trends, getaway, matchup, steal, luck, api
from app.services.live import lifespan

app = FastAPI(title="Sequence Baseball", lifespan=lifespan)

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

app.include_router(home.router)
app.include_router(par.router)
app.include_router(sequence.router)
app.include_router(trends.router)
app.include_router(getaway.router)
app.include_router(matchup.router)
app.include_router(steal.router)
app.include_router(luck.router)
app.include_router(api.router)
