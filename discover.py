"""
Discovery & Diagnostic Tool

Run locally to verify:
  1. The RSS feed works and returns entries
  2. Article pages expose author metadata (and which strategy finds it)
  3. Gelb/Varnes articles are correctly identified

Usage:
    pip install feedparser requests beautifulsoup4
    python discover.py
"""

import json
import re
import feedparser
import requests
from bs4 import BeautifulSoup

RSS_FEED = "https://www.nytimes.com/athletic/rss/mlb/phillies/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

WATCHED = ["matt gelb", "charlotte varnes"]


def probe_article(url: str) -> dict:
    """Fetch an article page and report all author-related signals found."""
    results = {"url": url, "strategies": {}}

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        results["error"] = str(e)
        return results

    soup = BeautifulSoup(resp.text, "html.parser")

    # Meta tags
    for label, selector in [
        ("meta[name=author]", {"name": "author"}),
        ("meta[article:author]", {"property": "article:author"}),
        ("meta[dc.creator]", {"name": "dc.creator"}),
        ("meta[og:article:author]", {"property": "og:article:author"}),
        ("meta[twitter:creator]", {"name": "twitter:creator"}),
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content", "").strip():
            results["strategies"][label] = tag["content"].strip()

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in (
                    "NewsArticle", "Article", "BlogPosting", "ReportageNewsArticle"
                ):
                    author = item.get("author")
                    if author:
                        results["strategies"]["json-ld"] = author
        except (json.JSONDecodeError, TypeError):
            continue

    # HTML byline
    for attr in ["class", "data-testid", "itemprop"]:
        for keyword in ["byline", "author", "AuthorName"]:
            el = soup.find(attrs={attr: re.compile(keyword, re.I)})
            if el:
                text = re.sub(r"^(By\s+)", "", el.get_text(strip=True), flags=re.I)
                if text and len(text) < 200:
                    key = f"html[{attr}~={keyword}]"
                    results["strategies"][key] = text

    return results


def main():
    print(f"{'='*60}")
    print(f"  RSS Feed: {RSS_FEED}")
    print(f"{'='*60}")

    feed = feedparser.parse(RSS_FEED)

    if feed.bozo and not feed.entries:
        print(f"  ❌ Feed error: {feed.bozo_exception}")
        return

    print(f"  ✅ {len(feed.entries)} entries")

    # Check if RSS itself has author data
    has_author = sum(1 for e in feed.entries if e.get("author") or getattr(e, "dc_creator", ""))
    print(f"  📊 {has_author}/{len(feed.entries)} have author in RSS (expected: 0)")

    # Probe first 5 articles for author metadata on the page
    print(f"\n{'='*60}")
    print(f"  Probing article pages for author metadata...")
    print(f"{'='*60}")

    for i, entry in enumerate(feed.entries[:5]):
        url = entry.get("link", "").split("?")[0]
        title = entry.get("title", "")[:50]

        print(f"\n  [{i+1}] {title}...")
        print(f"      URL: {url}")

        result = probe_article(url)

        if "error" in result:
            print(f"      ❌ Fetch error: {result['error']}")
            continue

        if not result["strategies"]:
            print(f"      ⚠️  No author metadata found on page")
            continue

        for strategy, value in result["strategies"].items():
            author_str = json.dumps(value) if isinstance(value, (dict, list)) else value
            is_match = any(w in author_str.lower() for w in WATCHED)
            marker = "🎯" if is_match else "  "
            print(f"      {marker} {strategy}: {author_str[:80]}")

    print(f"\n{'='*60}")
    print("Summary:")
    print("  • If you see author data via meta tags or JSON-LD, monitor.py will work as-is.")
    print("  • If only HTML byline works, it'll still work but is more fragile.")
    print("  • If nothing found, The Athletic may require auth to expose metadata.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
