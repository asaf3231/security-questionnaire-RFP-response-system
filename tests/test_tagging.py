"""
tests/test_tagging.py — auto-tagging at intake (app.pipeline.infer_tags).

ADD-only. Covers the deterministic tag-inference helper introduced for auto-tagging:
  - returns only valid-vocabulary tags (routing_map keys ∪ high_risk_tags)
  - score-weighted ordering, capped at AUTO_TAG_MAX, deterministic
  - REQUIRED red/negative cases (Metric Integrity #4): empty chunks → []; chunks whose
    tags are all outside the vocabulary → [] (the helper is NOT a constant)
  - integration over the real KB: an encryption question infers an on-topic tag; an
    indemnity question infers the high-risk `legal` tag (which would force routing).
"""

from __future__ import annotations

from app.config import AUTO_TAG_MAX
from app.kb import load_kb, load_policy_tags
from app.pipeline import infer_tags
from app.retrieval import Retriever
from app.schema import RetrievedChunk


def _chunk(chunk_id: str, tags: list[str], score: float, sensitivity: str = "public") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        question=None,
        answer="x",
        source=None,
        sensitivity=sensitivity,
        topic_tags=tags,
        approved=True,
        bm25_score=score,
    )


# A small, self-contained policy map so the unit tests don't depend on data/ values.
_POLICY = {
    "high_risk_tags": ["legal", "security"],
    "routing_map": {
        "legal": "legal",
        "security": "security",
        "encryption": "security",
        "infrastructure": "engineering",
        "data-handling": "security",
    },
}


def test_infer_tags_valid_vocabulary_only():
    """A tag absent from routing_map ∪ high_risk_tags is never returned."""
    chunks = [_chunk("c1", ["encryption", "not-a-real-tag"], 10.0)]
    assert infer_tags(chunks, _POLICY) == ["encryption"]


def test_infer_tags_score_weighted_and_capped():
    """Higher cumulative BM25 score ranks first; result is capped at AUTO_TAG_MAX."""
    chunks = [
        _chunk("c1", ["encryption", "infrastructure", "data-handling"], 11.0),
        _chunk("c2", ["data-handling"], 5.0),
        _chunk("c3", ["legal"], 1.0),
    ]
    out = infer_tags(chunks, _POLICY)
    assert len(out) <= AUTO_TAG_MAX
    # data-handling has the highest cumulative weight (11 + 5); it must rank first.
    assert out[0] == "data-handling"
    assert "legal" not in out  # lowest weight, pushed out by the AUTO_TAG_MAX cap (=3)


def test_infer_tags_deterministic():
    chunks = [
        _chunk("c1", ["encryption", "infrastructure"], 7.0),
        _chunk("c2", ["data-handling"], 7.0),
    ]
    assert infer_tags(chunks, _POLICY) == infer_tags(chunks, _POLICY)


def test_infer_tags_tie_break_is_alphabetical():
    """Equal scores break deterministically by tag name ascending."""
    chunks = [_chunk("c1", ["infrastructure", "data-handling", "encryption"], 4.0)]
    # all three share score 4.0 → alphabetical: data-handling, encryption, infrastructure
    assert infer_tags(chunks, _POLICY) == ["data-handling", "encryption", "infrastructure"]


# --- REQUIRED red/negative cases: the helper must be able to return nothing ---

def test_infer_tags_empty_chunks_returns_empty():
    assert infer_tags([], _POLICY) == []


def test_infer_tags_no_valid_tags_returns_empty():
    """Chunks whose tags are all outside the vocabulary → [] (not a constant)."""
    chunks = [_chunk("c1", ["off-topic", "another-bad-tag"], 9.0)]
    assert infer_tags(chunks, _POLICY) == []


# --- integration over the real synthetic KB ---

def test_infer_tags_integration_encryption_on_topic():
    retriever = Retriever(load_kb())
    policy_tags = load_policy_tags()
    chunks = retriever.retrieve("Does your platform encrypt customer data at rest?")
    tags = infer_tags(chunks, policy_tags)
    assert tags, "expected at least one inferred tag for a well-covered question"
    # the inferred tags must be on-topic for encryption/data-handling
    assert {"encryption", "data-handling", "infrastructure"} & set(tags)


def test_infer_tags_integration_indemnity_infers_high_risk_legal():
    """An indemnification question must infer the high-risk `legal` tag (→ would route)."""
    retriever = Retriever(load_kb())
    policy_tags = load_policy_tags()
    chunks = retriever.retrieve("Do you indemnify customers for security breaches?")
    tags = infer_tags(chunks, policy_tags)
    assert "legal" in tags
