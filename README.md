# athletic-discord-monitor

Posts new Matt Gelb and Charlotte Varnes articles from The Athletic to your Phillies Therapy Discord. Runs as a free GitHub Actions cron job.

## Setup (5 minutes)

### 1. Discover the RSS feed

Run locally to confirm the correct URL and that author filtering works:

```bash
pip install feedparser
python discover_feeds.py
```

Update `RSS_FEEDS` in `monitor.py` with whatever URL works.

### 2. Create a Discord webhook

1. **Server Settings → Integrations → Webhooks → New Webhook**
2. Name it, pick the target channel (e.g. `#news`)
3. Copy the webhook URL

### 3. Create the GitHub repo

```bash
git init athletic-discord-monitor
cd athletic-discord-monitor
# copy all files into this directory
git add .
git commit -m "Initial commit"
gh repo create athletic-discord-monitor --private --push
```

### 4. Add the webhook secret

```bash
gh secret set DISCORD_WEBHOOK_URL
# paste your webhook URL when prompted
```

Or: repo **Settings → Secrets and variables → Actions → New repository secret**

### 5. Done

The workflow runs every 15 minutes automatically. It:
1. Fetches the Phillies RSS feed
2. Filters for Gelb / Varnes articles
3. Posts new ones to Discord as rich embeds
4. Commits `posted_articles.json` back to the repo so it remembers what's been posted

You can trigger it manually from the **Actions** tab anytime.

## Adding more authors

Edit `WATCHED_AUTHORS` in `monitor.py`:

```python
WATCHED_AUTHORS = {
    "matt gelb":        {"display_name": "Matt Gelb",        "color": 0xC41E3A},
    "charlotte varnes": {"display_name": "Charlotte Varnes", "color": 0x002D72},
    "scott lauber":     {"display_name": "Scott Lauber",     "color": 0xFFD700},
}
```

## Cost

Zero. GitHub Actions free tier gives 2,000 min/month. This job uses ~1 min/month.
