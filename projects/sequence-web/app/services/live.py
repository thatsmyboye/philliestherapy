import asyncio
import json
import logging
from contextlib import asynccontextmanager
from collections import defaultdict
from typing import AsyncGenerator

from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Queues of SSE subscribers keyed by channel name (e.g. "par", "steal")
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(channel: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers[channel].append(q)
    return q


def unsubscribe(channel: str, q: asyncio.Queue) -> None:
    try:
        _subscribers[channel].remove(q)
    except ValueError:
        pass


async def broadcast(channel: str, data: dict) -> None:
    payload = json.dumps(data)
    dead = []
    for q in list(_subscribers[channel]):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unsubscribe(channel, q)


async def sse_generator(channel: str) -> AsyncGenerator[str, None]:
    q = subscribe(channel)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=25)
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                # keepalive comment
                yield ": keepalive\n\n"
    finally:
        unsubscribe(channel, q)


# ---------------------------------------------------------------------------
# Background polling tasks
# ---------------------------------------------------------------------------

async def _poll_live_games() -> None:
    """Poll live game feeds every 30 s and broadcast interesting events."""
    try:
        import statsapi
        from utils.mlb_data import get_team_abbreviations
    except Exception as exc:
        logger.warning("Live polling unavailable: %s", exc)
        return

    while True:
        try:
            games = statsapi.schedule(sportId=1)
            for game in games:
                if game.get("status") not in ("In Progress", "Warmup", "Pre-Game"):
                    continue
                gk = game.get("game_id")
                if not gk:
                    continue
                await broadcast("games", {
                    "game_pk": gk,
                    "away": game.get("away_name"),
                    "home": game.get("home_name"),
                    "away_score": game.get("away_score"),
                    "home_score": game.get("home_score"),
                    "inning": game.get("current_inning"),
                    "inning_half": game.get("inning_state"),
                    "status": game.get("status"),
                })
        except Exception as exc:
            logger.debug("Live poll error: %s", exc)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_live_games())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
