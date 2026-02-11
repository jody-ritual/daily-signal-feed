"""
RSS feed fetcher with keyword filtering and concurrent execution.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

from src.utils import clean_html, truncate, parse_date, hash_url, matches_keywords

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
MAX_WORKERS = 10
MAX_ARTICLE_AGE_DAYS = 7
USER_AGENT = "DailySignalFeed/1.0 (+https://github.com/daily-signal-feed)"


class RSSFetcher:
    """Fetches and parses RSS feeds with keyword filtering."""

    def __init__(self, keywords_file: str = "data/keywords.json"):
        self.keywords = self._load_keywords(keywords_file)

    def _load_keywords(self, filepath: str) -> dict:
        """Load keyword lists from JSON file."""
        path = Path(filepath)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        logger.warning(f"Keywords file not found: {filepath}")
        return {}

    def _resolve_keywords(self, feed_config: dict) -> list[str]:
        """Resolve a feed's keyword config to actual keyword list."""
        kw = feed_config.get("keywords", [])
        if isinstance(kw, str):
            # String reference to a keyword list name
            return self.keywords.get(kw, [])
        return kw  # Already a list (empty = no filter = include all)

    def fetch_feed(self, feed_config: dict) -> list[dict]:
        """Fetch and parse a single RSS feed."""
        url = feed_config["url"]
        name = feed_config["name"]
        category = feed_config.get("category", "news")
        feed_type = feed_config.get("type", "rss")

        # Skip non-RSS feeds (reddit, twitter handled separately)
        if feed_type != "rss" and feed_type not in (None, "rss"):
            return []

        keywords = self._resolve_keywords(feed_config)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)

        try:
            resp = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            if feed.bozo and not feed.entries:
                logger.warning(f"Feed '{name}' is malformed and has no entries.")
                return []

            articles = []
            for entry in feed.entries:
                pub_date = parse_date(entry)
                if not pub_date or pub_date < cutoff:
                    continue

                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                if not title or not link:
                    continue

                # Extract summary from various fields
                summary = ""
                for field in ("summary", "description", "content"):
                    val = entry.get(field)
                    if val:
                        if isinstance(val, list):
                            val = val[0].get("value", "") if val else ""
                        summary = clean_html(val)
                        break
                summary = truncate(summary)

                # Keyword filtering
                if keywords:
                    combined_text = f"{title} {summary}"
                    if not matches_keywords(combined_text, keywords):
                        continue

                articles.append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": name,
                    "category": category,
                    "published": pub_date,
                    "published_str": pub_date.strftime("%B %d, %Y"),
                    "hash": hash_url(link),
                    "type": "rss",
                    "engagement": None,
                    "is_trending": False,
                    "trend_score": 0.0,
                })

            logger.info(f"RSS: {len(articles)} articles from '{name}'")
            return articles

        except Exception as e:
            logger.warning(f"RSS: Failed to fetch '{name}' ({url}): {e}")
            return []

    def fetch_all(self, feeds: list[dict]) -> list[dict]:
        """Fetch all RSS feeds concurrently."""
        # Filter to only RSS-type feeds
        rss_feeds = [f for f in feeds if f.get("type", "rss") == "rss"]
        all_articles = []

        logger.info(f"RSS: Fetching {len(rss_feeds)} feeds...")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for feed in rss_feeds:
                future = executor.submit(self.fetch_feed, feed)
                futures[future] = feed["name"]

            for future in as_completed(futures):
                name = futures[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                except Exception as e:
                    logger.error(f"RSS: Error processing '{name}': {e}")

        logger.info(f"RSS: Total {len(all_articles)} articles from {len(rss_feeds)} feeds")
        return all_articles
