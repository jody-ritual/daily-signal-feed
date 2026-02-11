"""
Article deduplication using URL hashing and fuzzy title matching.
"""

import json
import logging
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)

SEEN_FILE = Path("data/seen_articles.json")
MAX_SEEN_ENTRIES = 10000
SIMILARITY_THRESHOLD = 0.85  # For fuzzy title matching


class Deduplicator:
    """Removes duplicate articles across builds using hash tracking."""

    def __init__(self, seen_file: str = str(SEEN_FILE)):
        self.seen_file = Path(seen_file)
        self.seen = self._load_seen()

    def _load_seen(self) -> set:
        """Load previously seen article hashes from disk."""
        if self.seen_file.exists():
            try:
                with open(self.seen_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Dedup: Corrupted seen file, starting fresh.")
        return set()

    def save_seen(self):
        """Persist seen hashes to disk (bounded size)."""
        trimmed = list(self.seen)[-MAX_SEEN_ENTRIES:]
        self.seen_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.seen_file, "w", encoding="utf-8") as f:
            json.dump(trimmed, f)
        logger.info(f"Dedup: Saved {len(trimmed)} seen hashes.")

    def _titles_similar(self, title1: str, title2: str) -> bool:
        """Check if two titles are similar enough to be duplicates."""
        if not title1 or not title2:
            return False
        ratio = SequenceMatcher(None, title1.lower(), title2.lower()).ratio()
        return ratio >= SIMILARITY_THRESHOLD

    def deduplicate(self, articles: list[dict]) -> list[dict]:
        """
        Remove duplicate articles:
        1. By URL hash (exact match against historical seen set)
        2. By fuzzy title matching within current batch
        """
        unique = []
        seen_this_run = set()
        titles_this_run = []

        for article in articles:
            h = article["hash"]

            # Skip if already seen in previous builds
            if h in self.seen:
                continue

            # Skip if seen in this run
            if h in seen_this_run:
                continue

            # Fuzzy title dedup within current batch
            title = article.get("title", "")
            is_dup = False
            for existing_title in titles_this_run:
                if self._titles_similar(title, existing_title):
                    is_dup = True
                    break

            if is_dup:
                continue

            unique.append(article)
            seen_this_run.add(h)
            titles_this_run.append(title)

        # Update seen set with new articles
        self.seen.update(seen_this_run)

        logger.info(
            f"Dedup: {len(articles)} → {len(unique)} articles "
            f"({len(articles) - len(unique)} duplicates removed)"
        )
        return unique
