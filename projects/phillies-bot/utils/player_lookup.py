"""
Fuzzy player name resolution → MLBAM player ID.

Uses statsapi.lookup_player for candidate search, then applies thefuzz for
ranking when multiple candidates come back.
"""
from __future__ import annotations

import re
from typing import Optional

import statsapi
from thefuzz import fuzz

# Ohtani has a single MLBAM ID used for both pitching and hitting queries.
OHTANI_ID = 660271


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower().strip())


def resolve_player(
    name: str,
    require_pitcher: bool = False,
    require_hitter: bool = False,
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Resolve a player name to an MLBAM ID.

    Returns (mlbam_id, full_name, error_message).
    On success, error_message is None. On failure, mlbam_id and full_name are None.

    require_pitcher / require_hitter filter the candidate list to players whose
    primary position includes pitching or hitting respectively.
    """
    name = name.strip()
    parts = name.split()

    # Try last-name-only for single tokens, last+first for multi-token.
    candidates: list[dict] = []
    if len(parts) == 1:
        candidates = statsapi.lookup_player(parts[0]) or []
    else:
        # statsapi.lookup_player searches fullName; try last name first
        candidates = statsapi.lookup_player(parts[-1]) or []
        if not candidates:
            candidates = statsapi.lookup_player(name) or []

    if not candidates:
        # Final fallback: search the full name string
        candidates = statsapi.lookup_player(name) or []

    if not candidates:
        return None, None, f'No player found matching "{name}". Try a different spelling.'

    # Score each candidate with fuzzy matching against the full input name.
    norm_input = _normalize(name)
    scored: list[tuple[int, dict]] = []
    for p in candidates:
        full = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
        score = fuzz.token_sort_ratio(norm_input, _normalize(full))
        scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Filter by role if requested.
    if require_pitcher or require_hitter:
        filtered = []
        for score, p in scored:
            pid = p.get("id")
            if pid == OHTANI_ID:
                filtered.append((score, p))
                continue
            pos = p.get("primaryPosition", {}).get("abbreviation", "")
            is_pitcher = pos == "P"
            if require_pitcher and is_pitcher:
                filtered.append((score, p))
            elif require_hitter and not is_pitcher:
                filtered.append((score, p))
        scored = filtered

        if not scored:
            role = "pitcher" if require_pitcher else "hitter"
            return None, None, (
                f'No {role} found matching "{name}". '
                f"Check the spelling or try a different name."
            )

    _, top = scored[0]
    mlbam_id = int(top["id"])
    full_name = f"{top.get('firstName', '').title()} {top.get('lastName', '').title()}".strip()
    return mlbam_id, full_name, None


def get_player_name_by_id(mlbam_id: int) -> Optional[str]:
    """Return a player's full name given their MLBAM ID, or None on failure."""
    try:
        data = statsapi.get("person", {"personId": mlbam_id})
        people = data.get("people", [])
        if people:
            return people[0].get("fullName")
    except Exception:
        pass
    return None
