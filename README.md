# Phillies Therapy

A multi-project repository for Philadelphia Phillies fan tools and automation, centered around Discord integration.

## Projects

### 1. **phillies-bot** — Discord Bot
A feature-rich Discord bot for the Phillies Therapy server, built with discord.py.

**Features:**
- **Velocity** — Pitch velocity analysis and fastball tracking
- **Luck** — Phillies team performance luck metrics and analysis
- **Monitor** — Live game monitoring: milestone and career-high alerts
- **Standings** — Live team standings and division updates
- **Remember** — `/remember` spotlights a random Phillies player from any season since 1883. Season stats ship in `data/remember_seasons.json` because the bot host is blocked by the MLB Stats API; rebuild it from anywhere else with `python scripts/build_remember_data.py` (the deploy workflow refreshes the current and previous season automatically)

**Setup:**
- Requires `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, and `ALERTS_CHANNEL_ID` environment variables (see `projects/phillies-bot/.env.example` for the full list)
- Install dependencies: `pip install -r projects/phillies-bot/requirements.txt`
- Run: `python projects/phillies-bot/bot.py`

---

### 2. **phillies-monitor** — Athletic Articles RSS Monitor
Automatically posts new Matt Gelb and Charlotte Varnes articles from The Athletic to Discord via webhook. Runs free on GitHub Actions (every 15 minutes).

**How it works:**
1. **RSS polling** — queries one per-author feed per watched writer
   (`nytimes.com/athletic/rss/author/<slug>/`)
2. **Co-byline merge** — a piece they wrote together appears in both feeds; it
   posts once, credited to both
3. **State tracking** — maintains `posted_articles.json` to avoid duplicates

Because each feed belongs to one writer, the author is implied and no article
page is ever fetched.

**Setup:**
1. Verify both author feeds are healthy:
   ```bash
   pip install feedparser requests
   python projects/phillies-monitor/discover.py
   ```

2. Create a Discord webhook: **Server Settings → Integrations → Webhooks → New Webhook** → copy the URL

3. Add the webhook as a GitHub secret: `gh secret set DISCORD_WEBHOOK_URL`

4. The workflow runs automatically every 15 minutes (configurable in `.github/workflows/`)

**Customization:**
Edit the `WATCHED_AUTHORS` dict in `monitor.py` to add or remove tracked authors.
Keys are the author's URL slug as it appears in their Athletic author page
(e.g. `matt-gelb`), not their display name.

**Note on scraping:** an earlier version polled the Phillies team feed, which
carries no author data, and fetched each article page to read the byline. In
September 2026 NYT put DataDome bot protection in front of article pages;
those fetches began returning a 403 challenge page, the byline lookup failed,
and every article was quietly filed as "not a watched author" while the
workflow still reported success. Two things prevent a silent repeat:
a feed that errors or returns zero entries now **fails the workflow run**
rather than looking like a quiet day, and the RSS endpoints themselves are not
behind DataDome.

---

## Cost

$0 for all projects. GitHub Actions free tier includes 2,000 min/month; the monitor uses ~1 min/month.
