# Phillies Therapy

A multi-project repository for Philadelphia Phillies fan tools and automation, centered around Discord integration.

## Projects

### 1. **phillies-bot** — Discord Bot
A feature-rich Discord bot for the Phillies Therapy server, built with discord.py.

**Features:**
- **Velocity** — Pitch velocity analysis and fastball tracking
- **Luck** — Phillies team performance luck metrics and analysis
- **Monitor** — Posts new articles from The Athletic by watched authors
- **Standings** — Live team standings and division updates
- **SP Grader** — Starting pitcher performance grading with the PAR model (see below)

**Setup:**
- Requires `DISCORD_TOKEN`, `CHANNEL_ID`, `LEADERBOARD_CHANNEL_ID`, and `SP_GRADER_CHANNEL_ID` environment variables
- Install dependencies: `pip install -r projects/phillies-bot/requirements.txt`
- Run: `python projects/phillies-bot/bot.py`

---

### 2. **phillies-monitor** — Athletic Articles RSS Monitor
Automatically posts new Matt Gelb and Charlotte Varnes articles from The Athletic RSS feed to Discord via webhook. Runs free on GitHub Actions (every 15 minutes).

**How it works:**
1. **RSS polling** — queries the Phillies feed for new articles
2. **Author extraction** — fetches each article page and extracts author from meta tags, JSON-LD, or HTML byline
3. **Filtering** — posts only articles by watched authors
4. **State tracking** — maintains `posted_articles.json` to avoid duplicates

**Setup:**
1. Verify the RSS feed and author detection:
   ```bash
   pip install feedparser requests beautifulsoup4
   python projects/phillies-monitor/discover.py
   ```

2. Create a Discord webhook: **Server Settings → Integrations → Webhooks → New Webhook** → copy the URL

3. Add the webhook as a GitHub secret: `gh secret set DISCORD_WEBHOOK_URL`

4. The workflow runs automatically every 15 minutes (configurable in `.github/workflows/`)

**Customization:**
Edit the `WATCHED_AUTHORS` dict in `monitor.py` to add or remove tracked authors.

---

## Pitcher Ace Rating (PAR)

PAR is a proprietary 0–100 single-game grading model for MLB starting pitchers. It combines traditional boxscore stats with Statcast pitch-level data to evaluate how well a starter performed on a given day.

### Components

Each component is scored 0–100, then multiplied by its weight. The seven weighted scores are summed to produce the final PAR.

| Component | Weight | What It Measures |
|---|---|---|
| Efficiency | 22% | Outs recorded vs. the maximum possible 27 (a complete game). Uses a nonlinear curve that rewards deep outings — 5 IP ≈ 55, 7 IP ≈ 82, 9 IP = 100. |
| Run Prevention | 24% | Earned runs allowed, converted to a per-9-inning ERA. Mapped via exponential decay: 0.00 ERA → 100, ~3.50 ERA → 70, 9.00+ ERA → 0. |
| Strikeout Rate | 14% | K/9 IP, normalized to a 0–15 K/9 scale with a soft power-curve floor so moderate strikeout rates still earn partial credit. |
| Walk Control | 14% | BB/9 IP (inverted). Exponential decay rewards command: 0 BB/9 → 100, ~3.5 BB/9 → 55, 7+ BB/9 → 0. |
| Strike/Ball Ratio | 10% | Strike% of all pitches thrown. League average (~62–64%) maps to roughly 60–70. Below 40% → 0, above 70% → 100. |
| CSW% | 8% | Called Strikes + Swinging Strikes / Total Pitches (sourced from Statcast). League average (~27–28%) → 50. Above 40% → 100. |
| Batted Ball Quality | 8% | Composite of average exit velocity and average launch angle on balls in play (Statcast). Lower exit velo is better; line-drive launch angles (10–25°) are penalized most. Falls back to neutral (50) when no BIP data is available. |

### Grade Scale

| PAR | Grade |
|---|---|
| 90–100 | S |
| 80–89 | A+ |
| 70–79 | A |
| 60–69 | B |
| 50–59 | C |
| 40–49 | D |
| 0–39 | F |

### Season PAR

The leaderboard's season PAR is an estimate derived from aggregate season stats (IP, ERA, K, BB, GS). Because CSW% and Batted Ball Quality are not available as season aggregates from the Stats API, those two components are omitted and the remaining weights are applied proportionally. Individual game PAR is always the authoritative measure.

---

## Cost

$0 for all projects. GitHub Actions free tier includes 2,000 min/month; the monitor uses ~1 min/month.
