#!/usr/bin/env python3
"""
Daily Signal Feed — Main Build Orchestrator

Fetches articles from RSS feeds, Reddit, and Twitter/X,
scores them for trends, generates an executive summary,
and builds a static site for GitHub Pages deployment.

Run: python -m src.build
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to path for imports
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.utils import setup_logging
from src.rss_fetcher import RSSFetcher
from src.reddit_fetcher import RedditFetcher
from src.twitter_scraper import fetch_twitter
from src.deduplicator import Deduplicator
from src.trend_scorer import TrendScorer
from src.summary_generator import SummaryGenerator
from src.html_generator import HTMLGenerator

logger = logging.getLogger(__name__)

DATA_DIR = ROOT_DIR / "data"
FEEDS_FILE = DATA_DIR / "feeds.json"


def load_config() -> dict:
    """Load feeds.json configuration."""
    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    setup_logging()
    logger.info("=" * 60)
    logger.info("Daily Signal Feed — Build Starting")
    logger.info("=" * 60)

    # 1. Load configuration
    config = load_config()
    feeds = config["feeds"]
    categories = config["categories"]
    twitter_searches = config.get("twitter_searches", [])

    logger.info(f"Config: {len(feeds)} feeds, {len(categories)} categories, {len(twitter_searches)} Twitter searches")

    # 2. Fetch RSS feeds
    logger.info("-" * 40)
    logger.info("Phase 1: Fetching RSS feeds...")
    rss_fetcher = RSSFetcher(keywords_file=str(DATA_DIR / "keywords.json"))
    rss_articles = rss_fetcher.fetch_all(feeds)

    # 3. Fetch Reddit
    logger.info("-" * 40)
    logger.info("Phase 2: Fetching Reddit...")
    reddit_fetcher = RedditFetcher(keywords_file=str(DATA_DIR / "keywords.json"))
    reddit_articles = reddit_fetcher.fetch_all(feeds)

    # 4. Scrape Twitter/X (graceful fallback)
    logger.info("-" * 40)
    logger.info("Phase 3: Scraping Twitter/X...")
    twitter_articles = []
    try:
        twitter_articles = fetch_twitter(twitter_searches)
    except Exception as e:
        logger.warning(f"Twitter scraping failed completely: {e}")
        logger.info("Continuing without Twitter data.")

    # 5. Combine all sources
    all_articles = rss_articles + reddit_articles + twitter_articles
    logger.info(f"Combined: {len(all_articles)} total articles "
                f"(RSS: {len(rss_articles)}, Reddit: {len(reddit_articles)}, Twitter: {len(twitter_articles)})")

    if not all_articles:
        logger.warning("No articles fetched from any source. Building empty site.")

    # 6. Deduplicate
    logger.info("-" * 40)
    logger.info("Phase 4: Deduplicating...")
    dedup = Deduplicator(seen_file=str(DATA_DIR / "seen_articles.json"))
    all_articles = dedup.deduplicate(all_articles)

    # 7. Score for trends
    logger.info("-" * 40)
    logger.info("Phase 5: Scoring trends...")
    scorer = TrendScorer(history_file=str(DATA_DIR / "trends_history.json"))
    all_articles = scorer.score_articles(all_articles)
    trending_topics = scorer.get_trending_topics(all_articles)

    # 8. Generate executive summary
    logger.info("-" * 40)
    logger.info("Phase 6: Generating summary...")
    summary_gen = SummaryGenerator()
    summary_data = summary_gen.generate(all_articles, trending_topics, categories)

    # 9. Build static site
    logger.info("-" * 40)
    logger.info("Phase 7: Building site...")
    generator = HTMLGenerator(categories)
    generator.generate(all_articles, summary_data)

    # 10. Save state files
    logger.info("-" * 40)
    logger.info("Phase 8: Saving state...")
    dedup.save_seen()
    scorer.save_history()

    # Done
    logger.info("=" * 60)
    logger.info(f"BUILD COMPLETE: {len(all_articles)} articles, "
                f"{summary_data['active_sources']} sources, "
                f"{summary_data['trending_count']} trending")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
