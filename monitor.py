"""
Athletic Phillies RSS → Discord Webhook

Monitors The Athletic's Phillies team RSS feed for new articles by
Matt Gelb and Charlotte Varnes. Posts matches to Discord via webhook.

State is tracked in posted_articles.json, committed back to the repo
by the GitHub Actions workflow after each run.
"""

import json
import os
import re
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

# The Athletic team RSS feeds to check.
# Run discover_feeds.py locally first to confirm the correct URL.
RSS_FEEDS = [
    "https://www.nytimes.com/athletic/rss/mlb/phillies/",
]

# Authors to watch — matched case-insensitively against RSS author fields.
# Keys are lowercase for matching; values configure the Discord embed.
WATCHED_AUTHORS = {
    "matt gelb": {
        "display_name": "Matt Gelb",
        "color": 0xC41E3A,  # Phillies red
    },
    "charlotte varnes": {
        "display_name": "Charlotte Varnes",
        "color": 0x002D72,  # Phillies blue
    },
}

STATE_FILE = Path(__file__).parent / "posted_articles.json"
WEBHOOK_USERNAME = "The Athletic"
POST_DELAY = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
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


def load_posted_ids() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("posted_ids", []))
    except (json.JSONDecodeError, IOError):
        return set()


def save_posted_ids(ids: set[str]) -> None:
    STATE_FILE.write_text(json.dumps({
        "posted_ids": sorted(ids),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# RSS
# ---------------------------------------------------------------------------

def fetch_and_filter(feed_url: str) -> list[Article]:
    log.info(f"Fetching: {feed_url}")
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        log.error(f"Feed error: {feed.bozo_exception}")
        return []

    log.info(f"Feed has {len(feed.entries)} entries")
    matched: list[Article] = []

    for entry in feed.entries:
        author_name = _get_author(entry)
        if not author_name:
            continue

        author_config = _match_author(author_name)
        if not author_config:
            continue

        url = entry.get("link", "").split("?")[0]
        title = entry.get("title", "").strip()
        if not url or not title:
            continue

        description = _clean_summary(entry)
        published = _get_published(entry)
        image_url = _get_image(entry)

        matched.append(Article(
            id=article_id(url),
            url=url,
            title=title,
            author=author_config["display_name"],
            description=description,
            published=published,
            image_url=image_url,
        ))

    log.info(f"Matched {len(matched)} article(s) by watched authors")
    return matched


def _get_author(entry) -> str:
    if hasattr(entry, "author") and entry.author:
        return entry.author
    if hasattr(entry, "authors") and entry.authors:
        names = [a.get("name", "") for a in entry.authors if a.get("name")]
        if names:
            return ", ".join(names)
    if hasattr(entry, "dc_creator") and entry.dc_creator:
        return entry.dc_creator
    return ""


def _match_author(author_name: str) -> dict | None:
    lower = author_name.lower().strip()
    for key, config in WATCHED_AUTHORS.items():
        if key in lower or lower in key:
            return config
    return None


def _clean_summary(entry) -> str:
    text = getattr(entry, "summary", "") or getattr(entry, "description", "")
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    for old, new in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"')]:
        text = text.replace(old, new)
    text = text.strip()
    return text[:297] + "..." if len(text) > 300 else text


def _get_published(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    return getattr(entry, "published", "")


def _get_image(entry) -> str:
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            url = m.get("url", "")
            if m.get("medium") == "image" or m.get("type", "").startswith("image"):
                return url
            if any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                return url
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href", enc.get("url", ""))
    return ""


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def post_to_discord(article: Article) -> bool:
    if not DISCORD_WEBHOOK_URL:
        log.error("DISCORD_WEBHOOK_URL not set")
        return False

    author_config = _match_author(article.author) or {}

    embed: dict = {
        "title": article.title[:256],
        "url": article.url,
        "color": author_config.get("color", 0x808080),
        "author": {"name": article.author},
        "footer": {"text": "The Athletic"},
    }
    if article.description:
        embed["description"] = article.description
    if article.published:
        embed["timestamp"] = article.published
    if article.image_url:
        embed["image"] = {"url": article.image_url}

    payload: dict = {"embeds": [embed], "username": WEBHOOK_USERNAME}

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 204:
            log.info(f"✅ Posted: {article.title} ({article.author})")
            return True
        if resp.status_code == 429:
            wait = resp.json().get("retry_after", 5)
            log.warning(f"Rate limited, waiting {wait}s")
            time.sleep(wait)
            return post_to_discord(article)
        log.error(f"Discord {resp.status_code}: {resp.text}")
        return False
    except requests.RequestException as e:
        log.error(f"Post failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    log.info("🔍 Checking for new Gelb / Varnes articles...")

    if not DISCORD_WEBHOOK_URL:
        log.error("Set DISCORD_WEBHOOK_URL as a GitHub Actions secret or env var")
        sys.exit(1)

    posted = load_posted_ids()
    new_count = 0

    for url in RSS_FEEDS:
        for article in fetch_and_filter(url):
            if article.id in posted:
                continue
            if post_to_discord(article):
                posted.add(article.id)
                new_count += 1
                time.sleep(POST_DELAY)

    save_posted_ids(posted)
    log.info(f"✅ Done. {new_count} new article(s) posted.")


if __name__ == "__main__":
    run()
