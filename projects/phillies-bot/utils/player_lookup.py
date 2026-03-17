"""
Fuzzy player name resolution → MLBAM player ID.

Uses pybaseball.playerid_lookup with fuzzy=True, then applies thefuzz for
additional ranking when multiple candidates come back.
"""
from __future__ import annotations

import re
from typing import Optional

import statsapi
from pybaseball import playerid_lookup
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

    # Try last-name-only lookup for single tokens, first+last for multi-token.
    if len(parts) == 1:
        results = playerid_lookup(parts[0], fuzzy=True)
    else:
        # pybaseball expects (last, first)
        results = playerid_lookup(parts[-1], " ".join(parts[:-1]), fuzzy=True)

    if results is None or results.empty:
        # Fallback: try all tokens as last name
        results = playerid_lookup(name, fuzzy=True)

    if results is None or results.empty:
        return None, None, f'No player found matching "{name}". Try a different spelling.'

    # Score each candidate with fuzzy matching against the full input name.
    full_names = results["name_last"] + " " + results["name_first"]
    scores = full_names.apply(lambda n: fuzz.token_sort_ratio(_normalize(name), _normalize(n)))
    results = results.copy()
    results["_score"] = scores
    results = results.sort_values("_score", ascending=False)

    # Filter by role if requested.
    if require_pitcher or require_hitter:
        valid_ids = _filter_by_role(
            results["key_mlbam"].tolist(),
            require_pitcher=require_pitcher,
            require_hitter=require_hitter,
        )
        results = results[results["key_mlbam"].isin(valid_ids)]
        if results.empty:
            role = "pitcher" if require_pitcher else "hitter"
            return None, None, f'No {role} found matching "{name}". Check the spelling or try a different name.'

    top = results.iloc[0]
    mlbam_id = int(top["key_mlbam"])
    full_name = f"{top['name_first'].title()} {top['name_last'].title()}"
    return mlbam_id, full_name, None


def _filter_by_role(
    candidate_ids: list[int],
    require_pitcher: bool,
    require_hitter: bool,
) -> list[int]:
    """
    Return only those IDs whose primary position matches the requested role.
    Ohtani is always included for both roles.
    """
    valid = []
    for mlbam_id in candidate_ids:
        if mlbam_id == OHTANI_ID:
            valid.append(mlbam_id)
            continue
        try:
            info = statsapi.lookup_player(mlbam_id)
            if not info:
                continue
            position = info[0].get("primaryPosition", {}).get("abbreviation", "")
            is_pitcher = position == "P"
            if require_pitcher and is_pitcher:
                valid.append(mlbam_id)
            elif require_hitter and not is_pitcher:
                valid.append(mlbam_id)
        except Exception:
            continue
    return valid
