"""
Run locally to find the correct Athletic RSS URL and verify author fields.

    pip install feedparser
    python discover_feeds.py
"""

import feedparser
import json

CANDIDATES = [
    "https://www.nytimes.com/athletic/rss/mlb/team/phillies-philadelphia/",
    "https://www.nytimes.com/athletic/rss/mlb/team/philadelphia-phillies/",
    "https://nytimes.com/athletic/rss/mlb/team/phillies-philadelphia/",
    "https://nytimes.com/athletic/rss/mlb/team/philadelphia-phillies/",
    "https://www.nytimes.com/athletic/rss/mlb/",
    "https://www.nytimes.com/athletic/rss/news/",
    "https://www.nytimes.com/athletic/rss/news",
]

WATCHED = ["matt gelb", "charlotte varnes"]


def check(url: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {url}")
    print(f"{'='*60}")

    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        print(f"  ❌ {feed.bozo_exception}")
        return
    if not feed.entries:
        print(f"  ⚠️  0 entries (title: {feed.feed.get('title', 'n/a')})")
        return

    print(f"  ✅ {len(feed.entries)} entries — {feed.feed.get('title', '')}")

    # Show first 3 entries with author info
    for i, e in enumerate(feed.entries[:3]):
        author = e.get("author") or getattr(e, "dc_creator", "") or "(none)"
        print(f"\n  [{i+1}] {e.get('title', '')[:70]}")
        print(f"      Author: {author}")
        print(f"      Link:   {e.get('link', '')[:80]}")

    # Count entries with author metadata
    has_author = sum(1 for e in feed.entries if e.get("author") or getattr(e, "dc_creator", ""))
    print(f"\n  📊 {has_author}/{len(feed.entries)} entries have author data")

    # Find watched author matches
    hits = []
    for e in feed.entries:
        a = (e.get("author") or getattr(e, "dc_creator", "") or "").lower()
        for w in WATCHED:
            if w in a:
                hits.append((w, e.get("title", "")[:50]))
    if hits:
        print(f"  🎯 {len(hits)} match(es):")
        for author, title in hits:
            print(f"     {author}: {title}")
    else:
        print(f"  ⚠️  No watched-author matches")


if __name__ == "__main__":
    for url in CANDIDATES:
        try:
            check(url)
        except Exception as ex:
            print(f"  ❌ {ex}")
    print(f"\n{'='*60}")
    print("Use the working URL in monitor.py RSS_FEEDS list.")
