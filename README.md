# athletic-discord-monitor

Posts new Matt Gelb and Charlotte Varnes articles from The Athletic to the Phillies Therapy Discord. Runs free on GitHub Actions.

## How it works

The Athletic's Phillies RSS feed (`nytimes.com/athletic/rss/mlb/phillies/`) publishes new articles but **no author data**. So the monitor uses a two-step approach:

1. **RSS** — polls the feed for new article URLs (stable, structured, no auth needed)
2. **Page fetch** — for each new URL, fetches the article page and extracts the author from `<meta name="author">`, JSON-LD, or HTML byline
3. **Filter** — if the author matches Gelb or Varnes, posts to Discord; otherwise skips
4. **State** — tracks both posted and skipped article IDs in `posted_articles.json`, committed back to the repo after each run

## Setup

### 1. Verify the feed & author detection work

```bash
pip install feedparser requests beautifulsoup4
python discover.py
```

This probes the RSS feed and fetches the first 5 article pages, reporting which author-detection strategies succeed. You need at least one strategy to return author names.

### 2. Create a Discord webhook

**Server Settings → Integrations → Webhooks → New Webhook** → pick the channel → copy the URL.

### 3. Push to GitHub

```bash
git init && git add . && git commit -m "init"
gh repo create athletic-discord-monitor --private --push
```

### 4. Add the secret

```bash
gh secret set DISCORD_WEBHOOK_URL
# paste your webhook URL when prompted
```

### 5. Done

The workflow runs every 15 minutes. Monitor it in the **Actions** tab. Trigger manually with **Run workflow** anytime.

## Adding authors

```python
WATCHED_AUTHORS = {
    "matt gelb":        {"display_name": "Matt Gelb",        "color": 0xC41E3A},
    "charlotte varnes": {"display_name": "Charlotte Varnes", "color": 0x002D72},
    "scott lauber":     {"display_name": "Scott Lauber",     "color": 0xFFD700},
}
```

## Cost

$0. GitHub Actions free tier = 2,000 min/month. This uses ~1 min/month.

## If author detection breaks

If The Athletic changes their page structure or starts requiring auth to serve meta tags, `discover.py` will show you exactly what's available. The fallback chain is: meta tags → JSON-LD → HTML byline. All three would have to break simultaneously.
