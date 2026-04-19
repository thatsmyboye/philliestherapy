import re

import statsapi
from fastapi import APIRouter
from thefuzz import fuzz

router = APIRouter()

OHTANI_ID = 660271


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower().strip())


@router.get("/api/pitcher-search")
async def pitcher_search(q: str = ""):
    q = q.strip()
    if len(q) < 2:
        return []

    try:
        parts = q.split()
        candidates = statsapi.lookup_player(parts[-1]) or []
        if len(parts) > 1 and not candidates:
            candidates = statsapi.lookup_player(q) or []
    except Exception:
        return []

    pitchers = [
        p for p in candidates
        if int(p.get("id", 0)) == OHTANI_ID
        or p.get("primaryPosition", {}).get("abbreviation", "") == "P"
    ]

    norm_q = _normalize(q)
    scored = []
    for p in pitchers:
        use_first = p.get("useName") or p.get("firstName", "")
        use_last = p.get("useLastName") or p.get("lastName", "")
        legal_first = p.get("firstName", "")
        legal_last = p.get("lastName", "")
        use_full = f"{use_first} {use_last}".strip()
        legal_full = f"{legal_first} {legal_last}".strip()
        score = max(
            fuzz.token_sort_ratio(norm_q, _normalize(use_full)),
            fuzz.token_sort_ratio(norm_q, _normalize(legal_full)),
        )
        display = f"{use_first.title()} {use_last.title()}".strip()
        scored.append((score, {"id": int(p["id"]), "name": display}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:8]]
