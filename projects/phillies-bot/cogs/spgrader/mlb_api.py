"""
MLB Stats API + Statcast client.
All endpoints are public — no auth required.
"""

import asyncio
import aiohttp
import logging
from datetime import date
from typing import Optional

log = logging.getLogger("mlb_api")

BASE = "https://statsapi.mlb.com/api/v1"
STATCAST_BASE = "https://baseballsavant.mlb.com"


class MLBClient:
    """Async wrapper around the free MLB Stats API and Baseball Savant."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "PhilliesTherapyBot/1.0"}
            )
        return self._session

    async def get(self, url: str, params: dict = None) -> dict:
        session = await self._get_session()
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self):
        if self._session:
            await self._session.close()

    # ─── Schedule ────────────────────────────────────────────────────────────

    async def get_todays_schedule(self, team_id: int, game_date: str = None) -> list[dict]:
        """Return today's (or given date's) games for a team."""
        if game_date is None:
            game_date = date.today().isoformat()
        data = await self.get(
            f"{BASE}/schedule",
            params={
                "sportId": 1,
                "teamId": team_id,
                "date": game_date,
                "gameType": "S,R",
                "hydrate": "linescore,decisions,pitchers",
            }
        )
        games = []
        for date_entry in data.get("dates", []):
            games.extend(date_entry.get("games", []))
        return games

    # ─── Live Feed ────────────────────────────────────────────────────────────

    async def get_live_feed(self, game_pk: int) -> dict:
        """Full live game data (gameData + liveData)."""
        return await self.get(
            f"{BASE}.1/game/{game_pk}/feed/live"
        )

    async def get_boxscore(self, game_pk: int) -> dict:
        return await self.get(f"{BASE}/game/{game_pk}/boxscore")

    # ─── Pitcher Details ─────────────────────────────────────────────────────

    async def get_pitcher_game_stats(self, game_pk: int, pitcher_id: int) -> Optional[dict]:
        """
        Parse boxscore for a specific pitcher's pitching line.
        Returns dict with: ip, h, r, er, bb, k, hr, bf, pitches, strikes
        """
        bs = await self.get_boxscore(game_pk)
        for side in ("home", "away"):
            players = bs.get("teams", {}).get(side, {}).get("players", {})
            key = f"ID{pitcher_id}"
            if key in players:
                p = players[key]
                stats = p.get("stats", {}).get("pitching", {})
                if stats:
                    return stats
        return None

    # ─── Statcast ─────────────────────────────────────────────────────────────

    async def get_statcast_game(self, game_pk: int, pitcher_id: int) -> list[dict]:
        """
        Fetch Statcast pitch-level data for a game/pitcher from Baseball Savant.
        Returns list of pitch dicts with exit_velocity, launch_angle, etc.
        """
        season = date.today().year
        url = (
            f"{STATCAST_BASE}/statcast_search/csv"
            f"?all=true&hfPT=&hfAB=&hfBBT=&hfPR=&hfZ=&stadium=&hfBBL=&hfNewZones=&"
            f"hfGT=R%7C&hfC=&hfSea={season}%7C&hfSit=&player_type=pitcher&"
            f"hfOuts=&opponent=&pitcher_throws=&batter_stands=&"
            f"hfSA=&game_date_gt=&game_date_lt=&"
            f"pitchers_lookup%5B%5D={pitcher_id}&"
            f"team=&position=&hfRO=&home_road=&"
            f"game_pk={game_pk}&hfFlag=&metric_1=&hfInn=&min_pitches=0&"
            f"min_results=0&group_by=name&sort_col=pitches&"
            f"player_event_sort=h_launch_speed&sort_order=desc&"
            f"min_abs=0&type=details&"
        )
        session = await self._get_session()
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.warning(f"Statcast CSV returned {resp.status}")
                    return []
                text = await resp.text()
                return self._parse_statcast_csv(text)
        except Exception as e:
            log.warning(f"Statcast fetch failed: {e}")
            return []

    def _parse_statcast_csv(self, csv_text: str) -> list[dict]:
        import csv, io
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = []
        for row in reader:
            rows.append(row)
        return rows

    # ─── League-wide starter stats ────────────────────────────────────────────

    async def get_league_starters_by_date(self, game_date: str) -> list[dict]:
        """
        Return a list of starting pitcher stats for all MLB games on the given
        date (YYYY-MM-DD).  Each entry is a dict with keys:
          name, team, ip, k, bb, er, h, pitches, win, loss
        Only includes pitchers who recorded at least 1 out.
        """
        data = await self.get(
            f"{BASE}/schedule",
            params={
                "sportId": 1,
                "date": game_date,
                "gameType": "R",
                "hydrate": "boxscore,pitchers,decisions",
            }
        )

        starters = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                status = game.get("status", {}).get("abstractGameState", "")
                if status not in ("Live", "Final"):
                    continue
                game_pk = game["gamePk"]
                teams = game.get("teams", {})
                try:
                    bs_data = await self.get(f"{BASE}/game/{game_pk}/boxscore")
                except Exception:
                    continue

                for side in ("home", "away"):
                    team_abbrev = teams.get(side, {}).get("team", {}).get("abbreviation", "???")
                    bs_team = bs_data.get("teams", {}).get(side, {})
                    pitcher_ids = bs_team.get("pitchers", [])
                    if not pitcher_ids:
                        continue
                    starter_id = pitcher_ids[0]
                    players = bs_team.get("players", {})
                    key = f"ID{starter_id}"
                    if key not in players:
                        continue
                    player = players[key]
                    stats = player.get("stats", {}).get("pitching", {})
                    if not stats or stats.get("outs", 0) < 1:
                        continue
                    ip_str = stats.get("inningsPitched", "0.0")
                    name = player.get("person", {}).get("fullName", "Unknown")

                    # Determine W/L from game decisions
                    decisions = game.get("decisions", {})
                    win_id = decisions.get("winner", {}).get("id")
                    loss_id = decisions.get("loser", {}).get("id")
                    result_str = "W" if starter_id == win_id else ("L" if starter_id == loss_id else "")

                    starters.append({
                        "name": name,
                        "team": team_abbrev,
                        "ip": ip_str,
                        "k": stats.get("strikeOuts", 0),
                        "bb": stats.get("baseOnBalls", 0),
                        "er": stats.get("earnedRuns", 0),
                        "h": stats.get("hits", 0),
                        "pitches": stats.get("pitchesThrown", 0),
                        "result": result_str,
                    })

        # Sort: most IP first, then most Ks
        def _sort_key(s):
            parts = str(s["ip"]).split(".")
            outs = int(parts[0]) * 3 + (int(parts[1]) if len(parts) > 1 else 0)
            return (outs, s["k"])

        starters.sort(key=_sort_key, reverse=True)
        return starters

    async def get_league_season_pitching_leaders(self, season: int, limit: int = 15) -> list[dict]:
        """
        Return the top starting pitcher season lines ranked by innings pitched.
        Each entry: name, team, ip, era, k, bb, w, l, games
        """
        data = await self.get(
            f"{BASE}/stats",
            params={
                "stats": "season",
                "group": "pitching",
                "gameType": "R",
                "season": season,
                "sportId": 1,
                "playerPool": "all",
                "limit": limit,
                "sortStat": "inningsPitched",
                "fields": (
                    "stats,splits,stat,player,team,"
                    "inningsPitched,era,strikeOuts,baseOnBalls,"
                    "wins,losses,gamesStarted"
                ),
            }
        )
        leaders = []
        for split in data.get("stats", [{}])[0].get("splits", []):
            stat = split.get("stat", {})
            player = split.get("player", {})
            team = split.get("team", {})
            gs = stat.get("gamesStarted", 0)
            if gs < 1:
                continue
            leaders.append({
                "name": player.get("fullName", "Unknown"),
                "team": team.get("abbreviation", "???"),
                "ip": stat.get("inningsPitched", "0.0"),
                "era": stat.get("era", "-.--"),
                "k": stat.get("strikeOuts", 0),
                "bb": stat.get("baseOnBalls", 0),
                "w": stat.get("wins", 0),
                "l": stat.get("losses", 0),
                "gs": gs,
            })
        return leaders

    # ─── Play-by-play (for CSW%) ─────────────────────────────────────────────

    async def get_pitcher_plays(self, game_pk: int, pitcher_id: int) -> list[dict]:
        """Return all at-bat events for a pitcher from the live feed."""
        feed = await self.get_live_feed(game_pk)
        plays = []
        for play in feed.get("liveData", {}).get("plays", {}).get("allPlays", []):
            matchup = play.get("matchup", {})
            if matchup.get("pitcher", {}).get("id") == pitcher_id:
                plays.append(play)
        return plays
