"""
Build (or refresh) data/remember_seasons.json, the bundled snapshot /remember
reads from. Run it anywhere that can reach statsapi.mlb.com (the bot host
can't — Akamai returns 406 for its IP):

    python scripts/build_remember_data.py            # every season, 1883–now
    python scripts/build_remember_data.py 2025 2026  # just these seasons

Seasons are merged into the existing file, so a season that fails to fetch
keeps whatever data it already had. Exits non-zero if any season failed.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.mlb_data import (  # noqa: E402
    REMEMBER_DATA_FILE,
    REMEMBER_HITTING_FIELDS,
    REMEMBER_PITCHING_FIELDS,
    compact_remember_player,
    fetch_phillies_season_player_stats,
)

FIRST_SEASON = 1883


def _fetch(year: int) -> tuple[int, list | None]:
    try:
        players = fetch_phillies_season_player_stats(year)
    except Exception as exc:
        print(f"  {year}: FAILED ({exc})")
        return year, None
    rows = sorted((compact_remember_player(p) for p in players), key=lambda r: r[1])
    print(f"  {year}: {len(rows)} players")
    return year, rows


def main(argv: list[str]) -> int:
    years = [int(a) for a in argv] or list(range(FIRST_SEASON, date.today().year + 1))

    seasons: dict[str, list] = {}
    if REMEMBER_DATA_FILE.exists():
        with open(REMEMBER_DATA_FILE, encoding="utf-8") as f:
            seasons = json.load(f).get("seasons", {})

    print(f"Fetching {len(years)} season(s)...")
    failed = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for year, rows in pool.map(_fetch, years):
            if rows is None:
                failed.append(year)
            elif rows:
                seasons[str(year)] = rows
            # An empty season (not started yet) is left out so the bot falls
            # back to a live fetch for it.

    # One season per line keeps diffs readable when a season is refreshed.
    lines = [
        "{",
        f'"hitting_fields": {json.dumps(REMEMBER_HITTING_FIELDS)},',
        f'"pitching_fields": {json.dumps(REMEMBER_PITCHING_FIELDS)},',
        '"seasons": {',
    ]
    ordered = sorted(seasons.items(), key=lambda kv: int(kv[0]))
    for i, (year, rows) in enumerate(ordered):
        sep = "," if i < len(ordered) - 1 else ""
        lines.append(f'"{year}": {json.dumps(rows, ensure_ascii=False, separators=(",", ":"))}{sep}')
    lines += ["}", "}"]

    tmp = REMEMBER_DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(REMEMBER_DATA_FILE)

    print(f"Wrote {len(seasons)} season(s) to {REMEMBER_DATA_FILE}")
    if failed:
        print(f"Failed seasons (kept previous data): {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
