"""
app/eval/rubric.py — Computed evaluation metrics for the Comet retrieval pipeline.

Responsibility: compute Recall@K and other metrics over labeled fixtures.
Every metric is computed from a labeled input — no value is hardcoded or fabricated
(RULE_NO_FABRICATED_METRIC).

Import-safe: no side effects at import — this module only defines functions.
"""

from __future__ import annotations

from typing import Any

from app.config import RETRIEVAL_TOP_K
from app.retrieval import retrieve


def compute_recall_at_k(
    fixtures: list[dict[str, Any]],
    k: int = RETRIEVAL_TOP_K,
) -> float:
    """Compute Recall@K over a list of labeled eval fixtures.

    For each fixture, Recall@K is 1.0 if at least one labeled-relevant chunk_id
    appears in the top-k results returned by retrieve(), otherwise 0.0.
    The macro-average across all fixtures is returned.

    RULE_NO_FABRICATED_METRIC: the score is derived entirely from retrieve() results
    and the labeled relevant_chunk_ids in the fixtures — never hardcoded.

    Parameters
    ----------
    fixtures:
        A list of dicts, each with:
          query: str
          relevant_chunk_ids: list[str]
          topic_tags: list[str]   (may be empty; passed to retrieve() as filter)
    k:
        The cutoff rank. Defaults to RETRIEVAL_TOP_K from config.

    Returns
    -------
    float
        The macro-average Recall@K across all fixtures.
        Returns 0.0 if fixtures is empty.
    """
    if not fixtures:
        return 0.0

    hits = 0
    for fixture in fixtures:
        query: str = fixture["query"]
        relevant_ids: set[str] = set(fixture["relevant_chunk_ids"])
        topic_tags: list[str] = fixture.get("topic_tags", [])

        results = retrieve(
            question=query,
            topic_tags=topic_tags if topic_tags else None,
            top_k=k,
        )
        retrieved_ids = {chunk.chunk_id for chunk in results}

        if retrieved_ids.intersection(relevant_ids):
            hits += 1

    return hits / len(fixtures)
