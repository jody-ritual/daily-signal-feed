"""
HTML site generator using Jinja2 templates.
Renders the static pages for GitHub Pages deployment.
"""

import logging
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.utils import relative_time

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
OUTPUT_DIR = ROOT_DIR / "docs"

SITE_TITLE = "Daily Signal Feed"
SITE_TAGLINE = "AI, Web3 & Emerging Trends"
BASE_URL = "/daily-signal-feed"
MAX_ARTICLES_HOMEPAGE = 120


class HTMLGenerator:
    """Generates the static site from templates and article data."""

    def __init__(self, categories: dict):
        self.categories = categories
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )
        # Register custom filters
        self.env.filters["relative_time"] = lambda dt: relative_time(dt)

    def _group_by_date(self, articles: list[dict]) -> list[tuple[str, list[dict]]]:
        """Group articles by publication date, sorted newest first."""
        groups = defaultdict(list)
        for article in articles:
            date_str = article.get("published_str", "Unknown")
            groups[date_str].append(article)

        sorted_groups = sorted(
            groups.items(),
            key=lambda x: x[1][0].get("published", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        return sorted_groups

    def _prepare_articles(self, articles: list[dict]) -> list[dict]:
        """Add computed fields to articles for template rendering."""
        for article in articles:
            pub = article.get("published")
            if pub:
                article["relative_time"] = relative_time(pub)
            else:
                article["relative_time"] = ""
        return articles

    def generate(
        self,
        articles: list[dict],
        summary_data: dict,
    ):
        """Generate all static pages."""
        # Prepare articles
        articles = self._prepare_articles(articles)

        # Sort by date descending
        articles.sort(
            key=lambda x: x.get("published", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )

        # Prepare shared template context
        source_count = len({a["source"] for a in articles})
        category_counts = defaultdict(int)
        for a in articles:
            category_counts[a.get("category", "uncategorized")] += 1

        build_time = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

        shared_ctx = {
            "base_url": BASE_URL,
            "site_title": SITE_TITLE,
            "site_tagline": SITE_TAGLINE,
            "categories": self.categories,
            "category_counts": dict(category_counts),
            "build_time": build_time,
            "total_articles": len(articles),
            "source_count": source_count,
            "summary": summary_data,
        }

        # Create output directories
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "category").mkdir(exist_ok=True)
        (OUTPUT_DIR / "css").mkdir(exist_ok=True)

        # Trending articles
        trending = [a for a in articles if a.get("is_trending")]
        trending.sort(key=lambda x: x.get("trend_score", 0), reverse=True)

        # Homepage
        homepage_articles = articles[:MAX_ARTICLES_HOMEPAGE]
        date_groups = self._group_by_date(homepage_articles)

        html = self.env.get_template("index.html").render(
            date_groups=date_groups,
            trending_articles=trending[:6],
            active_page="home",
            **shared_ctx,
        )
        (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")
        logger.info("Generated: index.html")

        # Archive
        all_date_groups = self._group_by_date(articles)
        html = self.env.get_template("archive.html").render(
            date_groups=all_date_groups,
            active_page="archive",
            **shared_ctx,
        )
        (OUTPUT_DIR / "archive.html").write_text(html, encoding="utf-8")
        logger.info("Generated: archive.html")

        # Category pages
        cat_template = self.env.get_template("category.html")
        for cat_id, cat_info in self.categories.items():
            cat_articles = [a for a in articles if a.get("category") == cat_id]

            cat_date_groups = self._group_by_date(cat_articles) if cat_articles else []
            cat_sources = len({a["source"] for a in cat_articles}) if cat_articles else 0

            html = cat_template.render(
                category_info=cat_info,
                category_key=cat_id,
                date_groups=cat_date_groups,
                cat_article_count=len(cat_articles),
                cat_source_count=cat_sources,
                active_page=cat_id,
                **shared_ctx,
            )
            (OUTPUT_DIR / "category" / f"{cat_id}.html").write_text(html, encoding="utf-8")
            logger.info(f"Generated: category/{cat_id}.html ({len(cat_articles)} articles)")

        # Copy static assets
        css_src = STATIC_DIR / "css" / "style.css"
        if css_src.exists():
            shutil.copy2(css_src, OUTPUT_DIR / "css" / "style.css")
            logger.info("Copied: css/style.css")

        logger.info(
            f"Site generated: {len(articles)} articles, "
            f"{source_count} sources, "
            f"{len(self.categories)} categories"
        )
