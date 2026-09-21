"""
Discovery & Diagnostic Tool

Run locally to verify:
  1. Each watched author's RSS feed is reachable and returns entries
  2. The feeds carry the fields the Discord embed needs
  3. Article pages are still blocked (the reason we use author feeds at all)

Usage:
    pip install feedparser requests
    python discover.py
"""

from datetime import datetime, timezone

import feedparser
import requests

from monitor import AUTHOR_FEED, WATCHED_AUTHORS, USER_AGENT, article_id


def check_feed(slug: str, config: dict) -> list:
    url = AUTHOR_FEED.format(slug=slug)
    print(f"\n{'='*66}")
    print(f"  {config['display_name']}  —  {url}")
    print(f"{'='*66}")

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ❌ Fetch failed: {e}")
        return []

    feed = feedparser.parse(resp.content)
    if not feed.entries:
        print(f"  ❌ No entries (bozo={feed.bozo}: {getattr(feed, 'bozo_exception', None)})")
        return []

    print(f"  ✅ {len(feed.entries)} entries — feed title: {feed.feed.get('title')!r}")

    # The embed needs a link, title, pubDate and (ideally) an image.
    missing = {"link": 0, "title": 0, "pubDate": 0, "image": 0}
    for e in feed.entries:
        if not e.get("link"):
            missing["link"] += 1
        if not e.get("title"):
            missing["title"] += 1
        if not getattr(e, "published_parsed", None):
            missing["pubDate"] += 1
        if not getattr(e, "media_content", None) and not getattr(e, "media_thumbnail", None):
            missing["image"] += 1
    for field, count in missing.items():
        marker = "  " if count == 0 else "⚠️ "
        print(f"      {marker} {field}: {count}/{len(feed.entries)} entries missing")

    print(f"\n  Most recent:")
    for e in feed.entries[:5]:
        link = (e.get("link") or "").split("?")[0]
        pp = getattr(e, "published_parsed", None)
        when = datetime(*pp[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d") if pp else "??"
        print(f"      {when}  [{article_id(link)}]  {(e.get('title') or '')[:52]}")

    return [(e.get("link") or "").split("?")[0] for e in feed.entries]


def check_article_page(url: str) -> None:
    """
    Article pages sit behind DataDome bot protection and return a 403 JS
    challenge. If this ever starts returning 200 again, the old byline-scraping
    approach would work too — but the author feeds are simpler either way.
    """
    print(f"\n{'='*66}")
    print(f"  Article page reachability (expected: 403 DataDome)")
    print(f"{'='*66}")
    print(f"  {url[:62]}")
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        server = resp.headers.get("server", "?")
        print(f"      status={resp.status_code}  server={server}  bytes={len(resp.content)}")
        if resp.status_code == 403:
            print(f"      ✅ Blocked as expected — author feeds are the right approach")
        else:
            print(f"      ℹ️  Unexpectedly reachable (status {resp.status_code})")
    except requests.RequestException as e:
        print(f"      ❌ {e}")


def main():
    newest = None
    for slug, config in WATCHED_AUTHORS.items():
        urls = check_feed(slug, config)
        if urls and newest is None:
            newest = urls[0]

    if newest:
        check_article_page(newest)

    print(f"\n{'='*66}")
    print("Summary:")
    print("  • Both feeds returning entries → monitor.py will work as-is.")
    print("  • A feed that 404s usually means the author's URL slug changed;")
    print("    update the key in WATCHED_AUTHORS in monitor.py.")
    print(f"{'='*66}")


if __name__ == "__main__":
    main()
