"""
News article deduplication via lightweight fuzzy token ratio similarity.

Articles with similarity score > 85 to any already-retained article are dropped.
Runs in microseconds without needing PyTorch or external model weights.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 85.0  # 0 to 100 scale in rapidfuzz


def _fuzzy_similarity(str1: str, str2: str) -> float:
    """Calculate token similarity score between two headlines."""
    try:
        from rapidfuzz import fuzz
        return float(fuzz.token_set_ratio(str1, str2))
    except ImportError:
        # Fallback to simple Jaccard set similarity if rapidfuzz is not yet installed
        words1 = set(str1.lower().split())
        words2 = set(str2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return (intersection / union) * 100.0


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Remove articles whose title is similar (> 85% score) to a previously retained article.
    Comparisons are done on `title` field only for speed.
    Returns a deduplicated list preserving original order of first occurrences.
    """
    if len(articles) <= 1:
        return articles

    kept: list[dict] = []
    for article in articles:
        title = article.get("title", "").strip()
        if not title:
            continue

        is_dup = False
        for kept_article in kept:
            kept_title = kept_article.get("title", "").strip()
            if _fuzzy_similarity(title, kept_title) >= _SIMILARITY_THRESHOLD:
                is_dup = True
                break

        if not is_dup:
            kept.append(article)

    removed = len(articles) - len(kept)
    if removed:
        logger.debug("Dedup removed %d/%d duplicate articles", removed, len(articles))

    return kept

