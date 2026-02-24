"""
RSS Feed Discovery & Inspection Tool

Run this locally to:
1. Find the correct Phillies RSS feed URL
2. See what fields are available (especially author fields)
3. Verify that Gelb/Varnes articles show up with filterable author metadata

Usage:
    pip install feedparser
    python discover_feeds.py
"""

import feedparser
import json

# Candidate URLs to try — The Athletic's pattern varies slightly
CANDIDATE_URLS = [
    "https://www.nytimes.com/athletic/rss/mlb/team/phillies-philadelphia/",
    "https://www.nytimes.com/athletic/rss/mlb/team/philadelphia-phillies/",
    "https://nytimes.com/athletic/rss/mlb/team/phillies-philadelphia/",
    "https://nytimes.com/athletic/rss/mlb/team/philadelphia-phillies/",
    "https://www.nytimes.com/athletic/rss/mlb/",
    "https://www.nytimes.com/athletic/rss/news/",
    "https://www.nytimes.com/athletic/rss/news",
    # Older theathletic.com domain patterns (may redirect)
    "https://theathletic.com/rss/mlb/team/phillies-philadelphia/",
    "https://theathletic.com/team/phillies/feed/",
]

WATCHED_AUTHORS = ["matt gelb", "charlotte varnes"]


def check_feed(url: str) -> None:
    print(f"\n{'='*70}")
    print(f"Trying: {url}")
    print(f"{'='*70}")

    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        print(f"  ❌ Failed: {feed.bozo_exception}")
        return

    if not feed.entries:
        print(f"  ⚠️  Feed parsed but has 0 entries")
        if feed.feed.get("title"):
            print(f"  Feed title: {feed.feed.title}")
        return

    print(f"  ✅ Feed title: {feed.feed.get('title', '(none)')}")
    print(f"  📄 {len(feed.entries)} entries")

    # Show the first few entries with author info
    print(f"\n  First 5 entries:")
    for i, entry in enumerate(feed.entries[:5]):
        title = entry.get("title", "(no title)")[:80]
        link = entry.get("link", "(no link)")

        # Gather all author-related fields
        author_fields = {}
        if hasattr(entry, "author") and entry.author:
            author_fields["author"] = entry.author
        if hasattr(entry, "authors") and entry.authors:
            author_fields["authors"] = [a.get("name", str(a)) for a in entry.authors]
        if hasattr(entry, "dc_creator"):
            author_fields["dc:creator"] = entry.dc_creator

        published = entry.get("published", "(no date)")

        print(f"\n  [{i+1}] {title}")
        print(f"      Link: {link}")
        print(f"      Published: {published}")
        print(f"      Author info: {json.dumps(author_fields) if author_fields else '(none found)'}")

        # Check if this matches a watched author
        all_author_text = " ".join(str(v) for v in author_fields.values()).lower()
        for watched in WATCHED_AUTHORS:
            if watched in all_author_text:
                print(f"      🎯 MATCH: {watched}")

    # Summary: how many entries have author data?
    has_author = sum(
        1 for e in feed.entries
        if (hasattr(e, "author") and e.author)
        or (hasattr(e, "authors") and e.authors)
        or (hasattr(e, "dc_creator") and e.dc_creator)
    )
    print(f"\n  📊 {has_author}/{len(feed.entries)} entries have author metadata")

    # Check for watched author matches across all entries
    matches = []
    for entry in feed.entries:
        author_text = ""
        if hasattr(entry, "author") and entry.author:
            author_text += entry.author.lower()
        if hasattr(entry, "authors") and entry.authors:
            author_text += " ".join(a.get("name", "").lower() for a in entry.authors)
        if hasattr(entry, "dc_creator"):
            author_text += (entry.dc_creator or "").lower()

        for watched in WATCHED_AUTHORS:
            if watched in author_text:
                matches.append((watched, entry.get("title", "")[:60]))

    if matches:
        print(f"\n  🎯 Found {len(matches)} articles by watched authors:")
        for author, title in matches:
            print(f"     - {author}: {title}")
    else:
        print(f"\n  ⚠️  No articles by watched authors found in this feed")


if __name__ == "__main__":
    print("Athletic RSS Feed Discovery Tool")
    print("Looking for Phillies feeds with Gelb/Varnes articles...\n")

    for url in CANDIDATE_URLS:
        try:
            check_feed(url)
        except Exception as e:
            print(f"  ❌ Exception: {e}")

    print(f"\n{'='*70}")
    print("Done! Use the working feed URL(s) in your monitor_rss.py config.")
    print(f"{'='*70}")
