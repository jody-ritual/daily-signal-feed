"""
Twitter/X scraper using Playwright headless browser.
No API access needed — scrapes X search results directly.
Designed to fail gracefully: if X blocks or Playwright isn't available,
the rest of the build pipeline continues without Twitter data.
"""

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.utils import hash_url, clean_html, truncate

logger = logging.getLogger(__name__)

MAX_TWEETS_PER_QUERY = 30
SCROLL_PAUSE = 2.5  # seconds between scrolls
REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 4.0
MAX_RETRIES = 2
BROWSER_TIMEOUT = 15000  # ms


class TwitterScraper:
    """
    Scrapes Twitter/X search results using Playwright headless browser.

    Falls back gracefully if:
    - Playwright is not installed
    - X blocks the request
    - Any network/parsing error occurs
    """

    def __init__(self):
        self.browser = None
        self.context = None

    async def _init_browser(self):
        """Initialize Playwright browser with stealth settings."""
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            logger.info("Twitter: Browser initialized.")
        except ImportError:
            logger.warning("Twitter: Playwright not installed. Skipping Twitter scraping.")
            raise
        except Exception as e:
            logger.warning(f"Twitter: Failed to init browser: {e}")
            raise

    async def _close_browser(self):
        """Clean up browser resources."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()

    async def _random_delay(self):
        """Random delay to avoid detection."""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        await asyncio.sleep(delay)

    async def search_query(self, query: str, category: str, max_results: int = 30) -> list[dict]:
        """
        Search X for a query and extract recent tweets.
        Returns list of article dicts matching the standard format.
        """
        url = f"https://x.com/search?q={query}&src=typed_query&f=live"
        articles = []

        for attempt in range(MAX_RETRIES + 1):
            try:
                page = await self.context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)

                # Wait for tweets to load
                await page.wait_for_timeout(3000)

                # Check for login wall or block
                content = await page.content()
                if "Log in" in content and "search" not in page.url:
                    logger.warning(f"Twitter: Login wall encountered for query '{query}'")
                    await page.close()
                    return []

                # Scroll to load more tweets
                tweets_data = []
                scroll_count = 0
                max_scrolls = 5

                while len(tweets_data) < max_results and scroll_count < max_scrolls:
                    # Extract tweet elements
                    tweet_elements = await page.query_selector_all('article[data-testid="tweet"]')

                    for elem in tweet_elements:
                        if len(tweets_data) >= max_results:
                            break
                        tweet = await self._extract_tweet(elem, category)
                        if tweet and tweet["hash"] not in {t["hash"] for t in tweets_data}:
                            tweets_data.append(tweet)

                    # Scroll down
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))
                    scroll_count += 1

                articles = tweets_data
                await page.close()
                logger.info(f"Twitter: {len(articles)} tweets for query '{query}'")
                break  # Success, exit retry loop

            except Exception as e:
                logger.warning(f"Twitter: Attempt {attempt + 1} failed for '{query}': {e}")
                try:
                    await page.close()
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    await self._random_delay()
                else:
                    logger.warning(f"Twitter: All retries exhausted for '{query}'")

        return articles

    async def _extract_tweet(self, element, category: str) -> dict | None:
        """Extract structured data from a tweet element."""
        try:
            # Get tweet text
            text_elem = await element.query_selector('div[data-testid="tweetText"]')
            text = ""
            if text_elem:
                text = await text_elem.inner_text()
                text = clean_html(text)

            if not text:
                return None

            # Get author
            author_elem = await element.query_selector('div[dir="ltr"] > span')
            author = ""
            if author_elem:
                author = await author_elem.inner_text()

            # Get link - try to find the tweet permalink
            time_elem = await element.query_selector("time")
            link = ""
            pub_date = datetime.now(timezone.utc)

            if time_elem:
                parent_link = await time_elem.evaluate(
                    '(el) => el.closest("a") ? el.closest("a").href : ""'
                )
                if parent_link:
                    link = parent_link

                datetime_attr = await time_elem.get_attribute("datetime")
                if datetime_attr:
                    try:
                        pub_date = datetime.fromisoformat(
                            datetime_attr.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

            if not link:
                link = f"https://x.com/search?q={text[:50]}"

            # Get engagement metrics (approximate from aria-labels)
            engagement = {"likes": 0, "retweets": 0, "replies": 0}
            for metric, testid in [
                ("replies", 'reply'),
                ("retweets", 'retweet'),
                ("likes", 'like'),
            ]:
                btn = await element.query_selector(f'button[data-testid="{testid}"]')
                if btn:
                    aria = await btn.get_attribute("aria-label") or ""
                    numbers = re.findall(r"[\d,]+", aria)
                    if numbers:
                        engagement[metric] = int(numbers[0].replace(",", ""))

            title = truncate(text, 120)

            return {
                "title": title,
                "link": link,
                "summary": truncate(text, 300),
                "source": f"Twitter @{author}" if author else "Twitter",
                "category": category,
                "published": pub_date,
                "published_str": pub_date.strftime("%B %d, %Y"),
                "hash": hash_url(link if "status" in link else f"tweet-{hash(text)}"),
                "type": "twitter",
                "author": author,
                "engagement": engagement,
                "is_trending": False,
                "trend_score": 0.0,
            }

        except Exception as e:
            logger.debug(f"Twitter: Failed to extract tweet: {e}")
            return None

    async def run_scrape(self, search_configs: list[dict]) -> list[dict]:
        """
        Main entry point. Runs all configured Twitter searches.
        Returns list of article dicts.
        """
        if not search_configs:
            logger.info("Twitter: No search configs provided.")
            return []

        all_tweets = []
        try:
            await self._init_browser()

            for config in search_configs:
                query = config.get("query", "")
                category = config.get("category", "social-buzz")
                max_results = config.get("max_results", MAX_TWEETS_PER_QUERY)

                tweets = await self.search_query(query, category, max_results)
                all_tweets.extend(tweets)
                await self._random_delay()

        except ImportError:
            logger.warning("Twitter: Playwright not available. Returning empty.")
            return []
        except Exception as e:
            logger.warning(f"Twitter: Scraper failed: {e}. Returning partial results.")
        finally:
            await self._close_browser()

        logger.info(f"Twitter: Total {len(all_tweets)} tweets scraped")
        return all_tweets


def fetch_twitter(search_configs: list[dict]) -> list[dict]:
    """Synchronous wrapper for the async Twitter scraper."""
    try:
        scraper = TwitterScraper()
        return asyncio.run(scraper.run_scrape(search_configs))
    except Exception as e:
        logger.warning(f"Twitter: Complete failure: {e}. Returning empty list.")
        return []
