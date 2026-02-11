"""
Trend scoring engine that surfaces emerging topics by analyzing
mention velocity, cross-source confirmation, and engagement signals.
"""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

TRENDS_FILE = Path("data/trends_history.json")
MAX_HISTORY_DAYS = 7
TOP_TRENDING_COUNT = 15

# Terms to ignore in trend extraction (too generic)
STOP_TERMS = {
    "the", "and", "for", "that", "this", "with", "from", "are", "was",
    "has", "have", "will", "can", "but", "not", "you", "all", "they",
    "their", "its", "our", "your", "one", "two", "new", "more", "how",
    "what", "when", "who", "why", "would", "could", "should",
    "about", "into", "than", "been", "just", "also", "some", "very",
    "most", "like", "over", "after", "before", "between", "under",
    "through", "during", "first", "last", "next", "other", "many",
    "much", "each", "every", "both", "any",
}


class TrendScorer:
    """
    Scores articles and terms by trend velocity to surface emerging topics.

    Scoring formula:
      score = velocity × cross_source_bonus × engagement_factor × temporal_weight

    Where:
    - velocity = (mentions_recent / avg_mentions_historical) or 2.0 if brand new
    - cross_source_bonus = 1.0 + 0.15 * (num_unique_sources - 1), capped at 2.0
    - engagement_factor = normalized engagement (1.0 default)
    - temporal_weight = recency decay (1.0 for <1h, 0.8 for 1-6h, 0.5 for 6-24h)
    """

    def __init__(self, history_file: str = str(TRENDS_FILE)):
        self.history_file = Path(history_file)
        self.history = self._load_history()
        self.current_mentions = Counter()
        self.current_sources = defaultdict(set)

    def _load_history(self) -> list[dict]:
        """Load trend history snapshots."""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Prune old entries
                    cutoff = (
                        datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_DAYS)
                    ).isoformat()
                    return [s for s in data if s.get("timestamp", "") >= cutoff]
            except (json.JSONDecodeError, TypeError):
                logger.warning("Trends: Corrupted history, starting fresh.")
        return []

    def save_history(self):
        """Save current trend snapshot to history."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mentions": dict(self.current_mentions.most_common(200)),
        }
        self.history.append(snapshot)

        # Prune old snapshots
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_DAYS)
        ).isoformat()
        self.history = [s for s in self.history if s.get("timestamp", "") >= cutoff]

        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2)
        logger.info(f"Trends: Saved snapshot with {len(self.current_mentions)} terms.")

    def _extract_terms(self, text: str) -> list[str]:
        """
        Extract significant terms from text.
        Focuses on capitalized words, known project names, and multi-word terms.
        """
        if not text:
            return []

        terms = []

        # Extract capitalized words and acronyms (likely project/company names)
        caps = re.findall(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*\b", text)
        for cap in caps:
            cleaned = cap.strip()
            if len(cleaned) >= 2 and cleaned.lower() not in STOP_TERMS:
                terms.append(cleaned)

        # Extract all-caps acronyms (AI, LLM, NFT, DeFi, etc.)
        acronyms = re.findall(r"\b[A-Z]{2,6}\b", text)
        for acr in acronyms:
            if acr.lower() not in STOP_TERMS:
                terms.append(acr)

        # Extract hashtag-style terms
        hashtags = re.findall(r"#(\w+)", text)
        terms.extend(hashtags)

        return terms

    def _get_historical_avg(self, term: str) -> float:
        """Get average mentions of a term across historical snapshots."""
        if not self.history:
            return 0.0

        counts = []
        for snapshot in self.history:
            mentions = snapshot.get("mentions", {})
            counts.append(mentions.get(term, 0))

        return sum(counts) / len(counts) if counts else 0.0

    def _calculate_velocity(self, term: str, current_count: int) -> float:
        """
        Calculate trend velocity:
        - Brand new term (no history): velocity = 2.0 (novelty boost)
        - Rising term: velocity = current / historical_avg
        - Stable term: velocity ≈ 1.0
        - Declining: velocity < 1.0
        """
        hist_avg = self._get_historical_avg(term)

        if hist_avg == 0:
            # New term — boost it
            return 2.0 if current_count >= 2 else 1.5

        velocity = current_count / hist_avg
        return min(velocity, 10.0)  # Cap extreme spikes

    def _temporal_weight(self, pub_date: datetime) -> float:
        """Apply recency weighting to articles."""
        now = datetime.now(timezone.utc)
        hours_old = (now - pub_date).total_seconds() / 3600

        if hours_old < 1:
            return 1.0
        elif hours_old < 6:
            return 0.85
        elif hours_old < 12:
            return 0.7
        elif hours_old < 24:
            return 0.5
        else:
            return 0.3

    def _engagement_factor(self, article: dict) -> float:
        """Calculate engagement factor from article metrics."""
        engagement = article.get("engagement")
        if not engagement:
            return 1.0

        likes = engagement.get("likes", 0)
        retweets = engagement.get("retweets", 0)
        replies = engagement.get("replies", 0)
        upvotes = engagement.get("upvotes", 0)

        total = likes + (retweets * 2) + replies + upvotes
        if total == 0:
            return 1.0

        # Log-scale normalization
        import math
        return 1.0 + math.log10(1 + total) * 0.2

    def score_articles(self, articles: list[dict]) -> list[dict]:
        """
        Score all articles and tag trending ones.
        Returns the same articles with trend_score and is_trending populated.
        """
        # Phase 1: Extract terms from all articles and count mentions
        for article in articles:
            text = f"{article.get('title', '')} {article.get('summary', '')}"
            terms = self._extract_terms(text)
            source = article.get("source", "")

            for term in terms:
                self.current_mentions[term] += 1
                self.current_sources[term].add(source)

        # Phase 2: Calculate term scores
        term_scores = {}
        for term, count in self.current_mentions.items():
            if count < 2:
                continue  # Skip single mentions

            velocity = self._calculate_velocity(term, count)
            num_sources = len(self.current_sources[term])
            cross_source = min(1.0 + 0.15 * (num_sources - 1), 2.0)

            term_scores[term] = velocity * cross_source

        # Phase 3: Score individual articles
        for article in articles:
            text = f"{article.get('title', '')} {article.get('summary', '')}"
            terms = self._extract_terms(text)

            # Article score = max term score × engagement × temporal
            max_term_score = max(
                (term_scores.get(t, 0.0) for t in terms), default=0.0
            )
            engagement = self._engagement_factor(article)
            temporal = self._temporal_weight(article.get("published", datetime.now(timezone.utc)))

            article["trend_score"] = round(max_term_score * engagement * temporal, 2)

        # Phase 4: Tag top articles as trending
        sorted_articles = sorted(articles, key=lambda a: a["trend_score"], reverse=True)
        trending_threshold = (
            sorted_articles[TOP_TRENDING_COUNT - 1]["trend_score"]
            if len(sorted_articles) >= TOP_TRENDING_COUNT
            else 0.5
        )

        for article in articles:
            article["is_trending"] = article["trend_score"] >= max(trending_threshold, 0.5)

        trending_count = sum(1 for a in articles if a["is_trending"])
        logger.info(f"Trends: {trending_count} articles flagged as trending")

        return articles

    def get_trending_topics(self, articles: list[dict]) -> list[dict]:
        """
        Return the top trending topics with metadata for the executive summary.
        """
        # Build term data
        term_data = {}
        for term, count in self.current_mentions.most_common(100):
            if count < 2:
                continue

            velocity = self._calculate_velocity(term, count)
            if velocity < 1.0:
                continue  # Not trending

            sources = list(self.current_sources[term])[:5]
            hist_avg = self._get_historical_avg(term)

            # Determine direction
            if hist_avg == 0:
                direction = "new"
            elif velocity > 1.5:
                direction = "up"
            elif velocity > 0.8:
                direction = "stable"
            else:
                direction = "down"

            num_sources = len(self.current_sources[term])
            cross_source = min(1.0 + 0.15 * (num_sources - 1), 2.0)
            score = velocity * cross_source

            term_data[term] = {
                "term": term,
                "mentions": count,
                "sources": sources,
                "num_sources": num_sources,
                "velocity": round(velocity, 2),
                "direction": direction,
                "score": round(score, 2),
            }

        # Sort by score and return top N
        sorted_topics = sorted(
            term_data.values(), key=lambda x: x["score"], reverse=True
        )
        return sorted_topics[:TOP_TRENDING_COUNT]
