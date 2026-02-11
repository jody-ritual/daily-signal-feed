"""
Shared utility functions for Daily Signal Feed.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone

import bleach

logger = logging.getLogger(__name__)

MAX_SUMMARY_LENGTH = 300


def setup_logging():
    """Configure logging for the build process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def hash_url(url: str) -> str:
    """Create a short hash of a URL for deduplication."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def clean_html(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = bleach.clean(text, tags=[], strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, max_len: int = MAX_SUMMARY_LENGTH) -> str:
    """Truncate text to max length, ending at word boundary."""
    if not text or len(text) <= max_len:
        return text
    truncated = text[:max_len].rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:") + "..."


def parse_date(entry) -> datetime | None:
    """Parse publication date from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def relative_time(dt: datetime) -> str:
    """Convert datetime to human-readable relative time string."""
    now = datetime.now(timezone.utc)
    diff = now - dt

    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks}w ago"
    return dt.strftime("%b %d, %Y")


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Check if text contains any of the given keywords (case-insensitive)."""
    if not keywords:
        return True
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def format_number(n: int) -> str:
    """Format large numbers with K/M suffixes."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
