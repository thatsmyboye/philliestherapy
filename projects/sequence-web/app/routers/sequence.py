import io
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")


@router.get("/sequence/", response_class=HTMLResponse)
async def sequence_index(request: Request):
    return templates.TemplateResponse("sequence/index.html", {
        "request": request,
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
    from utils.player_lookup import resolve_player
    from utils.mlb_data import get_pitcher_statcast
    from utils.sequence_calc import prepare_statcast_df, analyze_pitch_sequences

    error = None
    result = None
    player_id = None

    try:
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
        return templates.TemplateResponse("sequence/_results.html", {
            "request": request,
            "result": result,
            "error": error,
        })

    return templates.TemplateResponse("sequence/index.html", {
        "request": request,
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
    from utils.mlb_data import get_pitcher_statcast
    from utils.sequence_calc import prepare_statcast_df, analyze_pitch_sequences, create_sequence_chart_bytes

    rows = get_pitcher_statcast(int(pitcher_id))
    if not rows:
        return Response(status_code=404)

    df = prepare_statcast_df(rows)
    hand = batter_hand.upper() if batter_hand in ("R", "L") else None
    sequences_df = analyze_pitch_sequences(df, pitcher_name="", min_sample_size=15, batter_hand=hand)

    if sequences_df.empty:
        return Response(status_code=404)

    try:
        png_bytes = create_sequence_chart_bytes(sequences_df, metric=metric)
        return Response(content=png_bytes, media_type="image/png")
    except Exception:
        return Response(status_code=500)
