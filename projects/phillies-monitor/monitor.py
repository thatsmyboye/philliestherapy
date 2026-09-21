"""
Athletic Gelb / Varnes RSS → Discord Webhook

The Athletic publishes a per-author RSS feed, so we poll one feed per
watched writer and post everything that shows up:

  1. Poll each watched author's RSS feed for article URLs
  2. Post anything we haven't posted before

Previously this polled the Phillies team feed (which carries no author
data) and fetched each article page to read the byline. NYT put DataDome
bot protection in front of article pages in September 2026 — those fetches
now return a 403 challenge page, so the byline lookup silently failed and
every article was filed away as "not a watched author". Per-author feeds
remove the page fetch entirely, so there is nothing left to be blocked.
"""

import json
import os
import sys
import re
import time
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass

import feedparser
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

AUTHOR_FEED = "https://www.nytimes.com/athletic/rss/author/{slug}/"

WATCHED_AUTHORS = {
    "matt-gelb": {
        "display_name": "Matt Gelb",
        "color": 0xC41E3A,  # Phillies red
    },
    "charlotte-varnes": {
        "display_name": "Charlotte Varnes",
        "color": 0x002D72,  # Phillies blue
    },
}

STATE_FILE = Path(__file__).parent / "posted_articles.json"
STATE_VERSION = 2
WEBHOOK_USERNAME = "The Athletic"
POST_DELAY = 2

# Author feeds carry years of back catalog. Ignore anything older than this
# so a state-file mishap can never dump hundreds of old articles into Discord.
MAX_AGE_DAYS = 14

# Keep comfortably more IDs than the feeds hold (~750 combined) so a live
# article can never age out of state and get posted twice.
MAX_TRACKED_IDS = 3000

# One-time migration (see migrate_state). The team-feed monitor went blind on
# 2026-09-17; articles published from this date on were missed and should be
# posted when the new monitor first runs. Safe to delete this constant and
# migrate_state() once the migration has run in production.
BACKFILL_SINCE = datetime(2026, 9, 18, tzinfo=timezone.utc)

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
    color: int
    description: str = ""
    published: str = ""
    published_at: datetime | None = None
    image_url: str = ""


def article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# State — an insertion-ordered list of article IDs we've already handled.
# ---------------------------------------------------------------------------

def load_state() -> dict | None:
    """Returns None when there is no state file at all — i.e. a first run."""
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        log.error(f"Could not read {STATE_FILE.name} — refusing to run rather "
                  f"than risk reposting the back catalog")
        sys.exit(1)


def save_state(state: dict) -> None:
    state["version"] = STATE_VERSION
    # Newest IDs live at the end, so pruning from the front drops the oldest.
    if len(state["posted_ids"]) > MAX_TRACKED_IDS:
        state["posted_ids"] = state["posted_ids"][-MAX_TRACKED_IDS:]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


def migrate_state(state: dict, articles: list[Article]) -> dict:
    """
    Move a v1 (team-feed) state file to v2 (per-author feeds).

    v1 tracked the Phillies team feed: `posted_ids` plus a `skipped_ids` list
    of articles by other writers. Those skipped IDs are meaningless now — the
    author feeds only ever contain watched writers — so they're dropped.

    Everything currently in the author feeds is marked as already handled,
    except articles from BACKFILL_SINCE onwards, which the blinded monitor
    missed and which we want posted.
    """
    already_posted = set(state.get("posted_ids", []))

    seeded = [
        a.id for a in articles
        if a.id not in already_posted
        and not (a.published_at and a.published_at >= BACKFILL_SINCE)
    ]

    backfill = [
        a for a in articles
        if a.id not in already_posted
        and a.published_at and a.published_at >= BACKFILL_SINCE
    ]

    log.info(f"🔄 Migrating state to v{STATE_VERSION}: "
             f"{len(already_posted)} already posted, {len(seeded)} back-catalogue "
             f"articles seeded, {len(backfill)} to backfill")
    for a in backfill:
        log.info(f"   backfill: {a.author} — {a.title[:60]}")

    return {
        "version": STATE_VERSION,
        "posted_ids": sorted(already_posted) + seeded,
        "updated_at": state.get("updated_at", ""),
    }


# ---------------------------------------------------------------------------
# RSS: one feed per watched author
# ---------------------------------------------------------------------------

def get_author_articles(slug: str, config: dict) -> list[Article]:
    """
    Fetch one author's feed. Raises on anything that would make us silently
    post nothing — a blind monitor is worse than a loud failure.
    """
    url = AUTHOR_FEED.format(slug=slug)
    log.info(f"Fetching feed: {url}")

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()

    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise RuntimeError(f"{url} returned no entries "
                           f"(bozo={feed.bozo}: {getattr(feed, 'bozo_exception', None)})")

    log.info(f"  {config['display_name']}: {len(feed.entries)} entries")

    articles = []
    for e in feed.entries:
        link = (e.get("link") or "").split("?")[0]
        if not link:
            continue

        published_at = _parse_published(e)
        description = _clean_html(e.get("summary") or e.get("description") or "")

        image_url = ""
        if getattr(e, "media_content", None):
            for m in e.media_content:
                u = m.get("url", "")
                if m.get("medium") == "image" or u.lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                ):
                    image_url = u
                    break
        if not image_url and getattr(e, "media_thumbnail", None):
            image_url = e.media_thumbnail[0].get("url", "")

        articles.append(Article(
            id=article_id(link),
            url=link,
            title=(e.get("title") or "").strip(),
            author=config["display_name"],
            color=config["color"],
            description=description[:300],
            published=published_at.isoformat() if published_at else "",
            published_at=published_at,
            image_url=image_url,
        ))

    return articles


def merge_cobylines(articles: list[Article]) -> list[Article]:
    """
    Gelb and Varnes co-write regularly, so a shared piece shows up in both
    feeds. Collapse those to one article credited to both, in the order the
    authors are listed in WATCHED_AUTHORS.
    """
    merged: dict[str, Article] = {}
    for article in articles:
        existing = merged.get(article.id)
        if existing is None:
            merged[article.id] = article
        elif article.author not in existing.author:
            existing.author = f"{existing.author} & {article.author}"
    return list(merged.values())


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def post_to_discord(article: Article) -> bool:
    embed: dict = {
        "title": article.title[:256],
        "url": article.url,
        "color": article.color,
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

    articles: list[Article] = []
    for slug, config in WATCHED_AUTHORS.items():
        try:
            articles.extend(get_author_articles(slug, config))
        except (requests.RequestException, RuntimeError) as e:
            # Fail loudly: a broken feed used to look like "no new articles",
            # which is how this monitor stayed dead for four days.
            log.error(f"❌ Feed for {config['display_name']} is broken: {e}")
            sys.exit(1)

    articles = merge_cobylines(articles)

    # Oldest first, so a burst of posts reads in publication order.
    articles.sort(key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc))

    # First run: record everything currently in the feeds so we only post
    # genuinely new articles going forward — no back-catalogue spam.
    if state is None:
        save_state({"posted_ids": [a.id for a in articles], "updated_at": ""})
        log.info(f"🌱 First run — seeded {len(articles)} existing articles. "
                 f"Next run will only post new ones.")
        return

    migrating = state.get("version") != STATE_VERSION
    if migrating:
        state = migrate_state(state, articles)

    known = set(state["posted_ids"])
    tracked_before = len(state["posted_ids"])

    # On a migration run the seeded state already covers the whole back
    # catalogue, so the age guard would only block the intended backfill.
    cutoff = None if migrating else datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    new_posted = []
    for article in articles:
        if article.id in known:
            continue
        if cutoff and article.published_at and article.published_at < cutoff:
            log.info(f"  Skipping (older than {MAX_AGE_DAYS}d): {article.title[:60]}")
            known.add(article.id)
            state["posted_ids"].append(article.id)
            continue

        if post_to_discord(article):
            known.add(article.id)
            new_posted.append(article.id)
            time.sleep(POST_DELAY)

    state["posted_ids"].extend(new_posted)

    # Only rewrite the state file when something actually changed. Bumping a
    # timestamp on every run meant a commit and a push every 15 minutes, which
    # is what makes the workflow's push race with itself.
    if migrating or len(state["posted_ids"]) != tracked_before:
        save_state(state)
    else:
        log.info("No change — leaving state file untouched")

    log.info(f"✅ Done. {len(new_posted)} posted.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    for old, new in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                     ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"')]:
        text = text.replace(old, new)
    return text.strip()


def _parse_published(entry) -> datetime | None:
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


if __name__ == "__main__":
    run()
