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
- **SP Grader** — Starting pitcher performance grading

**Setup:**
- Requires `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` environment variables
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

## Cost

$0 for all projects. GitHub Actions free tier includes 2,000 min/month; monitor uses ~1 min/month.
