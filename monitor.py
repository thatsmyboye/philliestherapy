"""
Athletic Phillies RSS → Discord Webhook (with author lookup)

The Athletic's Phillies RSS feed has no author data, so:
  1. Poll the RSS feed for new article URLs
  2. For each new URL, fetch the article page and extract the author
     from meta tags / JSON-LD / HTML byline
  3. If the author matches a watched name, post to Discord

This is the hybrid approach: RSS for reliable article discovery,
a lightweight page fetch for author identification.
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
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

RSS_FEED = "https://www.nytimes.com/athletic/rss/mlb/phillies/"

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

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data
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


def article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# State — tracks both posted and skipped articles so we don't re-fetch
# pages for articles by other authors on every run.
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"posted_ids": [], "skipped_ids": [], "updated_at": ""}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        return {"posted_ids": [], "skipped_ids": [], "updated_at": ""}


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# RSS: discover new article URLs
# ---------------------------------------------------------------------------

def get_rss_entries() -> list[dict]:
    log.info(f"Fetching RSS: {RSS_FEED}")
    feed = feedparser.parse(RSS_FEED)

    if feed.bozo and not feed.entries:
        log.error(f"RSS error: {feed.bozo_exception}")
        return []

    log.info(f"RSS has {len(feed.entries)} entries")
    entries = []

    for e in feed.entries:
        url = (e.get("link") or "").split("?")[0]
        if not url:
            continue

        title = (e.get("title") or "").strip()
        description = _clean_html(e.get("summary") or e.get("description") or "")
        published = _parse_published(e)

        image_url = ""
        if hasattr(e, "media_content") and e.media_content:
            for m in e.media_content:
                u = m.get("url", "")
                if m.get("medium") == "image" or u.lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                ):
                    image_url = u
                    break
        if not image_url and hasattr(e, "media_thumbnail") and e.media_thumbnail:
            image_url = e.media_thumbnail[0].get("url", "")

        entries.append({
            "url": url,
            "title": title,
            "description": description[:300],
            "published": published,
            "image_url": image_url,
        })

    return entries


# ---------------------------------------------------------------------------
# Author extraction: fetch article page, read meta tags / JSON-LD / byline
# ---------------------------------------------------------------------------

def extract_author(url: str) -> str | None:
    """
    Fetch an article page and extract the author name.

    Tries in order of reliability:
      1. <meta name="author">
      2. <meta property="article:author">
      3. <meta name="dc.creator">
      4. JSON-LD @type NewsArticle/Article → author field
      5. HTML byline element (class/attr containing "byline" or "author")
    """
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"Could not fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Meta tags ---
    for selector in [
        {"name": "author"},
        {"property": "article:author"},
        {"name": "dc.creator"},
        {"property": "og:article:author"},
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()

    # --- JSON-LD ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in (
                    "NewsArticle", "Article", "BlogPosting", "ReportageNewsArticle"
                ):
                    return _parse_jsonld_author(item.get("author"))
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    # --- HTML byline ---
    for attr in ["class", "data-testid", "itemprop"]:
        for keyword in ["byline", "author", "AuthorName"]:
            el = soup.find(attrs={attr: re.compile(keyword, re.I)})
            if el:
                text = re.sub(r"^(By\s+)", "", el.get_text(strip=True), flags=re.I)
                if text and len(text) < 200:
                    return text

    log.warning(f"No author found for {url}")
    return None


def _parse_jsonld_author(author_field) -> str | None:
    if isinstance(author_field, str):
        return author_field
    if isinstance(author_field, dict):
        return author_field.get("name")
    if isinstance(author_field, list):
        names = [
            a.get("name", "") if isinstance(a, dict) else str(a)
            for a in author_field
        ]
        return ", ".join(n for n in names if n) or None
    return None


def match_author(author_str: str) -> dict | None:
    if not author_str:
        return None
    lower = author_str.lower()
    for key, config in WATCHED_AUTHORS.items():
        if key in lower:
            return config
    return None


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def post_to_discord(article: Article) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False

    config = match_author(article.author) or {}

    embed: dict = {
        "title": article.title[:256],
        "url": article.url,
        "color": config.get("color", 0x808080),
        "author": {"name": article.author},
        "footer": {"text": "The Athletic"},
    }
    if article.description:
        embed["description"] = article.description
    if article.published:
        embed["timestamp"] = article.published
    if article.image_url:
        embed["thumbnail"] = {"url": article.image_url}

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
        log.error(f"Discord post failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    log.info("🔍 Checking for new Gelb / Varnes articles...")

    if not DISCORD_WEBHOOK_URL:
        log.error("Set DISCORD_WEBHOOK_URL as a GitHub Actions secret")
        sys.exit(1)

    state = load_state()
    known_ids = set(state.get("posted_ids", []) + state.get("skipped_ids", []))
    new_posted = []
    new_skipped = []

    for entry in get_rss_entries():
        aid = article_id(entry["url"])
        if aid in known_ids:
            continue

        log.info(f"New article: {entry['title'][:60]}...")

        author = extract_author(entry["url"])
        if not author:
            log.info("  Could not determine author, skipping")
            new_skipped.append(aid)
            continue

        config = match_author(author)
        if not config:
            log.info(f"  Author '{author}' — not watched, skipping")
            new_skipped.append(aid)
            continue

        article = Article(
            id=aid,
            url=entry["url"],
            title=entry["title"],
            author=config["display_name"],
            description=entry.get("description", ""),
            published=entry.get("published", ""),
            image_url=entry.get("image_url", ""),
        )

        if post_to_discord(article):
            new_posted.append(aid)
            time.sleep(POST_DELAY)

    # Update state
    state["posted_ids"] = sorted(set(state.get("posted_ids", [])) | set(new_posted))
    state["skipped_ids"] = sorted(set(state.get("skipped_ids", [])) | set(new_skipped))

    # Prune skipped list to prevent unbounded growth
    if len(state["skipped_ids"]) > 500:
        state["skipped_ids"] = state["skipped_ids"][-500:]

    save_state(state)
    log.info(f"✅ Done. {len(new_posted)} posted, {len(new_skipped)} skipped.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    for old, new in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"')]:
        text = text.replace(old, new)
    return text.strip()


def _parse_published(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    return getattr(entry, "published", "")


if __name__ == "__main__":
    run()
