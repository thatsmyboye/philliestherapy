"""
Athletic Phillies RSS → Discord Webhook (Author Filter)

Instead of scraping individual author pages (fragile, paywall issues),
this monitors The Athletic's Phillies team RSS feed and filters for
articles by specific authors.

RSS feeds are structured, public, and stable — no authentication needed,
no HTML parsing, no React hydration to deal with.

Designed to run on a cron schedule (e.g., every 15 minutes) on Railway.
"""

import json
import os
import sys
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass

import feedparser
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# The Athletic Phillies team RSS feed
# Pattern confirmed from other teams: nytimes.com/athletic/rss/{sport}/team/{slug}/
RSS_FEEDS = [
    "https://www.nytimes.com/athletic/rss/mlb/team/phillies-philadelphia/",
    # You could add more feeds to cast a wider net — some Gelb/Varnes
    # articles might appear under general MLB or news feeds:
    # "https://www.nytimes.com/athletic/rss/mlb/",
]

# Authors to watch for (matched case-insensitively against RSS author fields)
WATCHED_AUTHORS = {
    "matt gelb": {
        "display_name": "Matt Gelb",
        "color": 0xC41E3A,   # Phillies red
        "avatar_url": "",     # Optional headshot
    },
    "charlotte varnes": {
        "display_name": "Charlotte Varnes",
        "color": 0x002D72,   # Phillies blue
        "avatar_url": "",
    },
}

STATE_FILE = os.environ.get(
    "STATE_FILE", str(Path(__file__).parent / "posted_articles.json")
)

WEBHOOK_USERNAME = "The Athletic – Phillies"
WEBHOOK_AVATAR = ""  # Optional logo URL

POST_DELAY = 2  # seconds between Discord posts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Article:
    id: str
    url: str
    title: str
    author: str
    description: str = ""
    published: str = ""
    image_url: str = ""


# ---------------------------------------------------------------------------
# State management (swap for PostgreSQL version from README if desired)
# ---------------------------------------------------------------------------

def load_posted_ids() -> set[str]:
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        return set(data.get("posted_ids", []))
    except (json.JSONDecodeError, IOError):
        return set()


def save_posted_ids(ids: set[str]) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump({
            "posted_ids": sorted(ids),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)


def make_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# RSS parsing with author filtering
# ---------------------------------------------------------------------------

def fetch_and_filter(feed_url: str) -> list[Article]:
    """
    Fetch an RSS feed, return only articles by watched authors.

    feedparser handles all the XML parsing. A typical Athletic RSS entry has:
      - title
      - link
      - author / dc:creator  (the field we filter on)
      - summary / description
      - published / pubDate
      - media:content or enclosure (images)
    """
    logger.info(f"Fetching RSS: {feed_url}")
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        logger.error(f"Feed parse error: {feed.bozo_exception}")
        return []

    logger.info(f"Feed has {len(feed.entries)} total entries")

    matched: list[Article] = []

    for entry in feed.entries:
        # --- Extract author ---
        # feedparser normalizes author fields into entry.author (string)
        # and entry.authors (list of dicts with 'name' key).
        # The Athletic may use <dc:creator>, <author>, or <managingEditor>.
        author_name = _get_author(entry)

        if not author_name:
            continue

        # Check if this author is one we're watching
        author_key = author_name.lower().strip()
        author_config = None
        for watched_key, config in WATCHED_AUTHORS.items():
            if watched_key in author_key or author_key in watched_key:
                author_config = config
                break

        if not author_config:
            continue

        # --- Extract article metadata ---
        url = entry.get("link", "").split("?")[0]  # strip tracking params
        if not url:
            continue

        title = entry.get("title", "").strip()
        if not title:
            continue

        # Description / summary
        description = ""
        if hasattr(entry, "summary"):
            description = entry.summary
        elif hasattr(entry, "description"):
            description = entry.description
        # Strip HTML tags from description
        if description:
            description = _strip_html(description)
            # Truncate for embed
            if len(description) > 300:
                description = description[:297] + "..."

        # Published date — feedparser gives us a parsed time tuple
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                published = dt.isoformat()
            except (TypeError, ValueError):
                pass
        elif hasattr(entry, "published"):
            published = entry.published

        # Image — check media:content, media:thumbnail, enclosures
        image_url = _get_image(entry)

        matched.append(Article(
            id=make_id(url),
            url=url,
            title=title,
            author=author_config["display_name"],
            description=description,
            published=published,
            image_url=image_url,
        ))

    logger.info(f"Found {len(matched)} article(s) by watched authors")
    return matched


def _get_author(entry) -> str:
    """Extract author name from an RSS entry using multiple fallbacks."""
    # feedparser's normalized .author field
    if hasattr(entry, "author") and entry.author:
        return entry.author

    # .authors list (feedparser parses multiple authors)
    if hasattr(entry, "authors") and entry.authors:
        names = [a.get("name", "") for a in entry.authors if a.get("name")]
        if names:
            return ", ".join(names)

    # dc:creator (common in WordPress/Athletic feeds)
    if hasattr(entry, "dc_creator"):
        return entry.dc_creator

    return ""


def _get_image(entry) -> str:
    """Extract an image URL from RSS entry media fields."""
    # media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for media in entry.media_content:
            if media.get("medium") == "image" or media.get("type", "").startswith("image"):
                return media.get("url", "")
            # Some feeds don't specify medium but still have image URLs
            url = media.get("url", "")
            if url and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                return url

    # media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")

    # enclosures (used by some feeds for images)
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href", enc.get("url", ""))

    return ""


def _strip_html(text: str) -> str:
    """Minimal HTML tag stripping without importing extra libs."""
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    clean = clean.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return clean.strip()


# ---------------------------------------------------------------------------
# Discord webhook posting
# ---------------------------------------------------------------------------

def post_to_discord(article: Article) -> bool:
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL is not set!")
        return False

    # Look up author config for embed color
    author_key = article.author.lower()
    author_config = WATCHED_AUTHORS.get(author_key, {})
    # Fuzzy match if exact key doesn't work
    if not author_config:
        for key, config in WATCHED_AUTHORS.items():
            if key in author_key or author_key in key:
                author_config = config
                break

    embed = {
        "title": article.title[:256],
        "url": article.url,
        "color": author_config.get("color", 0x808080),
        "author": {"name": article.author},
        "footer": {"text": "The Athletic"},
    }

    if article.description:
        embed["description"] = article.description[:4096]
    if article.published:
        embed["timestamp"] = article.published
    if article.image_url:
        embed["image"] = {"url": article.image_url}
    if author_config.get("avatar_url"):
        embed["author"]["icon_url"] = author_config["avatar_url"]

    payload = {"embeds": [embed]}
    if WEBHOOK_USERNAME:
        payload["username"] = WEBHOOK_USERNAME
    if WEBHOOK_AVATAR:
        payload["avatar_url"] = WEBHOOK_AVATAR

    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 204:
            logger.info(f"✅ Posted: {article.title} ({article.author})")
            return True
        elif resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 5)
            logger.warning(f"Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            return post_to_discord(article)
        else:
            logger.error(f"Discord {resp.status_code}: {resp.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"Discord post failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    logger.info("🔍 Checking Athletic RSS for Gelb/Varnes articles...")

    if not DISCORD_WEBHOOK_URL:
        logger.error(
            "Set DISCORD_WEBHOOK_URL to your Discord webhook URL.\n"
            "Create one: Server Settings → Integrations → Webhooks → New Webhook"
        )
        sys.exit(1)

    posted_ids = load_posted_ids()
    new_count = 0

    for feed_url in RSS_FEEDS:
        articles = fetch_and_filter(feed_url)

        for article in articles:
            if article.id in posted_ids:
                logger.debug(f"Already posted: {article.title}")
                continue

            if post_to_discord(article):
                posted_ids.add(article.id)
                new_count += 1
                time.sleep(POST_DELAY)

    save_posted_ids(posted_ids)
    logger.info(f"✅ Done. {new_count} new article(s) posted.")


if __name__ == "__main__":
    run()
