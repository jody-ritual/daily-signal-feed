"""
Executive summary generator for the Daily Signal Feed homepage.
Produces structured data for the summary widget.
"""

import logging
from collections import Counter
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SummaryGenerator:
    """Generates executive summary data from scored articles and trending topics."""

    def generate(
        self,
        articles: list[dict],
        trending_topics: list[dict],
        categories: dict,
    ) -> dict:
        """
        Generate executive summary data structure.

        Returns dict with:
        - trending_topics: top trending terms with metadata
        - category_stats: article counts and activity per category
        - top_sources: most active sources
        - total_articles: total count
        - active_sources: unique source count
        - trending_count: number of trending articles
        - momentum: overall trend direction
        - build_time: formatted timestamp
        """
        # Category stats
        category_counts = Counter()
        for article in articles:
            category_counts[article.get("category", "uncategorized")] += 1

        max_count = max(category_counts.values()) if category_counts else 1

        category_stats = []
        for cat_id, cat_info in categories.items():
            count = category_counts.get(cat_id, 0)
            category_stats.append({
                "id": cat_id,
                "label": cat_info["label"],
                "color": cat_info["color"],
                "count": count,
                "pct": round((count / max_count) * 100) if max_count > 0 else 0,
            })

        # Sort by count descending
        category_stats.sort(key=lambda x: x["count"], reverse=True)

        # Top sources
        source_counts = Counter(a.get("source", "") for a in articles)
        top_sources = [
            {"name": name, "count": count}
            for name, count in source_counts.most_common(8)
        ]

        # Unique sources
        unique_sources = len(set(a.get("source", "") for a in articles))

        # Trending count
        trending_count = sum(1 for a in articles if a.get("is_trending", False))

        # Calculate momentum
        momentum = self._calculate_momentum(trending_topics)

        # Build time
        build_time = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

        summary = {
            "trending_topics": trending_topics[:10],
            "category_stats": category_stats,
            "top_sources": top_sources,
            "total_articles": len(articles),
            "active_sources": unique_sources,
            "trending_count": trending_count,
            "momentum": momentum,
            "build_time": build_time,
        }

        logger.info(
            f"Summary: {len(articles)} articles, "
            f"{unique_sources} sources, "
            f"{trending_count} trending, "
            f"momentum={momentum}"
        )

        return summary

    def _calculate_momentum(self, trending_topics: list[dict]) -> str:
        """
        Determine overall trend momentum:
        - 'accelerating': most trending topics are new or rising fast
        - 'active': mix of rising and stable
        - 'steady': mostly stable topics
        - 'quiet': few trending topics
        """
        if not trending_topics:
            return "quiet"

        directions = [t.get("direction", "stable") for t in trending_topics[:10]]
        up_count = directions.count("up") + directions.count("new")
        stable_count = directions.count("stable")

        total = len(directions)
        if total == 0:
            return "quiet"

        up_ratio = up_count / total

        if up_ratio > 0.6:
            return "accelerating"
        elif up_ratio > 0.3:
            return "active"
        elif stable_count > total * 0.5:
            return "steady"
        else:
            return "quiet"
