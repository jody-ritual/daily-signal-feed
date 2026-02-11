"""
Reddit fetcher using native RSS feeds (no API key needed).
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
MAX_WORKERS = 5
MAX_ARTICLE_AGE_DAYS = 3  # Reddit posts age quickly
USER_AGENT = "DailySignalFeed/1.0 (Reddit RSS Reader)"


class RedditFetcher:
    """Fetches Reddit posts via native RSS feeds."""

    def __init__(self, keywords_file: str = "data/keywords.json"):
        self.keywords = self._load_keywords(keywords_file)

    def _load_keywords(self, filepath: str) -> dict:
        path = Path(filepath)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _resolve_keywords(self, feed_config: dict) -> list[str]:
        kw = feed_config.get("keywords", [])
        if isinstance(kw, str):
            return self.keywords.get(kw, [])
        return kw

    def fetch_subreddit(self, feed_config: dict) -> list[dict]:
        """Fetch posts from a single subreddit via RSS."""
        url = feed_config["url"]
        name = feed_config["name"]
        category = feed_config.get("category", "social-buzz")
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
                logger.warning(f"Reddit: Feed '{name}' is malformed.")
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

                # Reddit RSS includes HTML content in summary
                summary = ""
                raw_summary = entry.get("summary", "") or entry.get("content", [{}])
                if isinstance(raw_summary, list):
                    raw_summary = raw_summary[0].get("value", "") if raw_summary else ""
                summary = clean_html(raw_summary)
                summary = truncate(summary, 400)

                # Extract author
                author = entry.get("author", "")
                if author.startswith("/u/"):
                    author = author[3:]

                # Keyword filtering
                if keywords:
                    combined = f"{title} {summary}"
                    if not matches_keywords(combined, keywords):
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
                    "type": "reddit",
                    "author": author,
                    "engagement": None,  # RSS doesn't include upvotes
                    "is_trending": False,
                    "trend_score": 0.0,
                })

            logger.info(f"Reddit: {len(articles)} posts from '{name}'")
            return articles

        except Exception as e:
            logger.warning(f"Reddit: Failed to fetch '{name}' ({url}): {e}")
            return []

    def fetch_all(self, feeds: list[dict]) -> list[dict]:
        """Fetch all Reddit subreddit RSS feeds concurrently."""
        reddit_feeds = [f for f in feeds if f.get("type") == "reddit"]
        all_articles = []

        if not reddit_feeds:
            logger.info("Reddit: No Reddit feeds configured.")
            return []

        logger.info(f"Reddit: Fetching {len(reddit_feeds)} subreddits...")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for feed in reddit_feeds:
                future = executor.submit(self.fetch_subreddit, feed)
                futures[future] = feed["name"]

            for future in as_completed(futures):
                name = futures[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                except Exception as e:
                    logger.error(f"Reddit: Error processing '{name}': {e}")

        logger.info(f"Reddit: Total {len(all_articles)} posts from {len(reddit_feeds)} subreddits")
        return all_articles
