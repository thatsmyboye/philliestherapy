import io
import logging
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/sequence/", response_class=HTMLResponse)
async def sequence_index(request: Request):
    return templates.TemplateResponse(request, "sequence/index.html", {
        "active_nav": "sequence",
        "result": None,
        "error": None,
        "pitcher_name": "",
        "batter_hand": "",
        "metric": "overall",
    })


@router.post("/sequence/", response_class=HTMLResponse)
async def sequence_search(
    request: Request,
    pitcher_name: str = Form(...),
    batter_hand: str = Form(""),
    metric: str = Form("overall"),
):
    error = None
    result = None
    player_id = None

    try:
        from utils.player_lookup import resolve_player
        from utils.mlb_data import get_pitcher_statcast
        from utils.sequence_calc import prepare_statcast_df, analyze_pitch_sequences

        player_id, resolved_name, lookup_err = resolve_player(pitcher_name, require_pitcher=True)
        if player_id is None:
            raise ValueError(lookup_err or f"Could not find pitcher '{pitcher_name}'")

        rows = get_pitcher_statcast(player_id)
        if not rows:
            raise ValueError(f"No Statcast data found for {resolved_name} this season.")

        df = prepare_statcast_df(rows)
        hand = batter_hand.upper() if batter_hand in ("R", "L") else None
        sequences_df = analyze_pitch_sequences(
            df,
            pitcher_name=resolved_name,
            min_sample_size=15,
            success_metric=metric,
            batter_hand=hand,
        )

        if sequences_df.empty:
            raise ValueError(f"Not enough sequence data for {resolved_name} (min 15 occurrences per sequence).")

        rows_out = sequences_df.head(8).to_dict("records")
        result = {
            "pitcher_name": resolved_name,
            "pitcher_id": player_id,
            "sequences": rows_out,
            "metric": metric,
            "batter_hand": batter_hand,
            "total_pitches": len(df),
        }
    except Exception as exc:
        error = str(exc)

    # HTMX partial or full page
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "sequence/_results.html", {
            "result": result,
            "error": error,
        })

    return templates.TemplateResponse(request, "sequence/index.html", {
        "active_nav": "sequence",
        "result": result,
        "error": error,
        "pitcher_name": pitcher_name,
        "batter_hand": batter_hand,
        "metric": metric,
    })


@router.get("/sequence/chart/{pitcher_id}.png")
async def sequence_chart(
    pitcher_id: int,
    batter_hand: str = "",
    metric: str = "overall",
):
    try:
        from utils.mlb_data import get_pitcher_statcast
        from utils.sequence_calc import prepare_statcast_df, analyze_pitch_sequences, create_sequence_chart_bytes

        rows = get_pitcher_statcast(int(pitcher_id))
        if not rows:
            return Response(status_code=404)

        df = prepare_statcast_df(rows)
        hand = batter_hand.upper() if batter_hand in ("R", "L") else None
        sequences_df = analyze_pitch_sequences(
            df, pitcher_name="", min_sample_size=15, success_metric=metric, batter_hand=hand
        )

        if sequences_df.empty:
            return Response(status_code=404)

        png_bytes = create_sequence_chart_bytes(sequences_df, pitcher_name="", batter_hand=hand)
        return Response(content=png_bytes.getvalue(), media_type="image/png")
    except Exception as exc:
        logger.error("Chart generation failed for pitcher %s: %s", pitcher_id, exc, exc_info=True)
        return Response(status_code=500)
