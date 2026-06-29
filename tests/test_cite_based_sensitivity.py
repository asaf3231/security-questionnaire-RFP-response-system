"""
tests/test_cite_based_sensitivity.py — cite-based sensitivity routing (trigger 4).

NEW additive coverage (RULE_GRADED_ARTIFACT_LOCK: adding files is allowed). Exercises
the cite-based sensitivity gate: trigger 4 fires on internal/restricted chunks the answer
actually CITED, not merely ones that rode along in the retrieval window — aligning routing
with the cite-based export gate (app/export.py).

The offline MockLLM cites its entire retrieval layer (app/llm.py), so the existing
deterministic suite cannot distinguish cite-based from retrieval-based behavior. These cases
pass an explicit `cited_chunk_ids` to exercise the selective-citation behavior the live lane
produces — the required red/green pair for the changed gate (META-FALSIFY).

Offline, deterministic; no network, no .env, no Claude API.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers (self-contained — no cross-test-module imports)
# ---------------------------------------------------------------------------

def _make_chunk(chunk_id, answer, bm25_score=1.0, sensitivity="public"):
    from app.schema import RetrievedChunk
    return RetrievedChunk(
        chunk_id=chunk_id,
        answer=answer,
        question=None,
        sensitivity=sensitivity,
        topic_tags=[],
        approved=True,
        bm25_score=bm25_score,
    )


def _make_item(topic_tags=None):
    from app.schema import QuestionnaireItem
    return QuestionnaireItem(
        item_id="cb-i1",
        question="How do you secure data?",
        topic_tags=topic_tags or [],
    )


def _make_confidence(score=0.85):
    from app.schema import ConfidenceResult
    return ConfidenceResult(score=score, rationale="test")


def _make_policy_tags():
    return {
        "sensitivity_tags": ["public", "internal", "restricted"],
        "high_risk_tags": ["legal", "security"],
        "routing_map": {
            "legal": "legal",
            "security": "security",
            "compliance": "security",
            "infrastructure": "engineering",
        },
    }


# ---------------------------------------------------------------------------
# Cite-based sensitivity routing — the i1/i2/i6 demo-live fix
# ---------------------------------------------------------------------------

class TestSensitivityRoutingCiteBased:
    """Trigger 4 keys off CITED chunks, not the full retrieval set.

    Each case isolates trigger 4: no high-risk tag (trigger 1), a clear BM25 gap
    (trigger 2), high confidence (trigger 3), grounded=True default (trigger 5).
    """

    def test_uncited_internal_chunk_does_not_route(self):
        """A RETRIEVED-but-UNCITED internal chunk must not trigger sensitivity routing.

        This is the i1/i2/i6 fix: a public, grounded answer whose internal neighbor
        merely rode along in the top-k is a confident auto-draft, not a review.
        """
        from app.routing import route_for_review
        from app.config import AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["infrastructure"])  # not high-risk
        chunks = [
            _make_chunk("kb-pub-cb1", "AES-256 at rest; public whitepaper.",
                        sensitivity="public", bm25_score=8.0),
            _make_chunk("kb-int-cb1", "Data residency regions (internal).",
                        sensitivity="internal", bm25_score=8.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.85)  # high → trigger 3 silent
        policy_tags = _make_policy_tags()

        # Answer cites ONLY the public chunk; the internal neighbor is uncited.
        decision = route_for_review(
            item, chunks, confidence, policy_tags, cited_chunk_ids={"kb-pub-cb1"}
        )

        assert decision.should_route is False, (
            "An uncited internal chunk must not trigger sensitivity routing under cite-based gating"
        )
        assert decision.reason_code is None
        assert decision.queue is None

    def test_cited_internal_chunk_routes(self):
        """An internal chunk the answer CITES still triggers ROUTED_SENSITIVE (protection kept)."""
        from app.routing import route_for_review
        from app.config import ROUTED_SENSITIVE, SENSITIVITY_REVIEW_QUEUE, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["infrastructure"])
        chunks = [
            _make_chunk("kb-pub-cb2", "Public summary.", sensitivity="public", bm25_score=8.0),
            _make_chunk("kb-int-cb2", "Internal vendor list.",
                        sensitivity="internal", bm25_score=8.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.85)
        policy_tags = _make_policy_tags()

        decision = route_for_review(
            item, chunks, confidence, policy_tags, cited_chunk_ids={"kb-pub-cb2", "kb-int-cb2"}
        )

        assert decision.should_route is True
        assert decision.reason_code == ROUTED_SENSITIVE
        assert decision.queue == SENSITIVITY_REVIEW_QUEUE

    def test_cited_restricted_chunk_routes(self):
        """A restricted chunk the answer CITES triggers ROUTED_SENSITIVE."""
        from app.routing import route_for_review
        from app.config import ROUTED_SENSITIVE, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["data-handling"])
        chunks = [
            _make_chunk("kb-pub-cb3", "Public posture.", sensitivity="public", bm25_score=7.0),
            _make_chunk("kb-res-cb3", "Coverage amounts under NDA.",
                        sensitivity="restricted", bm25_score=7.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.88)
        policy_tags = _make_policy_tags()

        decision = route_for_review(
            item, chunks, confidence, policy_tags, cited_chunk_ids={"kb-res-cb3"}
        )

        assert decision.reason_code == ROUTED_SENSITIVE

    def test_cited_chunk_ids_none_preserves_retrieval_based_behavior(self):
        """Omitting cited_chunk_ids preserves the legacy all-chunks behavior (backward compat).

        Every pre-existing caller that does not pass cited_chunk_ids must stay byte-identical —
        the DN-QA50 PR-1 `grounded=True` default precedent.
        """
        from app.routing import route_for_review
        from app.config import ROUTED_SENSITIVE, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["infrastructure"])
        chunks = [
            _make_chunk("kb-pub-cb4", "Public summary.", sensitivity="public", bm25_score=8.0),
            _make_chunk("kb-int-cb4", "Internal residency.",
                        sensitivity="internal", bm25_score=8.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.85)
        policy_tags = _make_policy_tags()

        # No cited_chunk_ids → legacy behavior: any retrieved internal chunk routes.
        decision = route_for_review(item, chunks, confidence, policy_tags)

        assert decision.reason_code == ROUTED_SENSITIVE, (
            "Without cited_chunk_ids the gate must keep its legacy retrieval-based behavior"
        )
