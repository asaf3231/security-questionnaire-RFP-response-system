"""
tests/test_dn_qa50_pr1_pr2.py — DN-QA50 PR-1 (stranded-draft routing) + PR-2 (contentless-question
fail-closed). ADD-ONLY (RULE_GRADED_ARTIFACT_LOCK): a NEW file; no existing test/fixture modified.

PR-1 (app/routing.py + app/config.py): grounding failure becomes a 5th, ABSOLUTE-LOWEST-precedence
  routing trigger (`ROUTED_UNGROUNDED`), so an ungrounded draft never strands un-reviewed
  (RULE_GROUNDED_ONLY: "⇒ UNGROUNDED_PLACEHOLDER + route"). The new `grounded` kwarg defaults True →
  every pre-PR-1 caller is byte-identical. Lowest precedence → it never relabels an item that
  triggers 1–4 already caught (preserves eval-006 = ROUTED_LOW_CONFIDENCE and all routed gold).
PR-2 (app/draft.py): a contentless question (zero significant tokens, e.g. "What about it?") fails
  grounding condition 4 CLOSED instead of skipping it (the prior `if question_tokens:` failed OPEN,
  letting an explicit non-answer ship as auto-confident). Single-token questions are unaffected.
"""

from __future__ import annotations

from app.config import (
    DEFAULT_REVIEWER_QUEUE,
    GROUNDING_FAIL,
    ROUTED_HIGH_RISK,
    ROUTED_LOW_CONFIDENCE,
    ROUTED_SENSITIVE,
    ROUTED_UNGROUNDED,
    UNGROUNDED_PLACEHOLDER,
)
from app.draft import grounding_check
from app.routing import route_for_review
from app.schema import (
    Citation,
    ConfidenceResult,
    ContextStack,
    DraftAnswer,
    QuestionnaireItem,
    RetrievedChunk,
)


def _chunk(cid, answer, bm25=5.0, sensitivity="public", topic_tags=None):
    return RetrievedChunk(
        chunk_id=cid, answer=answer, sensitivity=sensitivity,
        topic_tags=topic_tags or [], approved=True, bm25_score=bm25,
    )


def _policy():
    return {"high_risk_tags": ["legal", "security"],
            "routing_map": {"legal": "legal", "security": "security"}}


# clear bm25 gap (5.0 vs 1.0 → 4.0 ≥ AMBIGUITY_SCORE_MARGIN) so the ambiguity trigger never fires here
_CLEAR = [_chunk("c1", "alpha", bm25=5.0), _chunk("c2", "beta", bm25=1.0)]


# --------------------------------------------------------------------------- PR-1
class TestPR1RoutedUngrounded:
    def test_reason_code_constant(self):
        assert ROUTED_UNGROUNDED == "ROUTED_UNGROUNDED"

    def test_ungrounded_with_no_other_trigger_routes(self):
        # public, non-high-risk tag, conf ≥ 0.50, public chunks, clear bm25 gap → ONLY trigger 5
        item = QuestionnaireItem(item_id="x", question="q", topic_tags=["access-control"])
        d = route_for_review(item, _CLEAR, ConfidenceResult(score=0.593), _policy(), grounded=False)
        assert d.should_route is True
        assert d.reason_code == ROUTED_UNGROUNDED
        assert d.queue == DEFAULT_REVIEWER_QUEUE  # access-control not in routing_map → §9 fallback

    def test_grounded_default_is_byte_identical(self):
        # default grounded=True with the SAME inputs must NOT route (pre-PR-1 behavior preserved)
        item = QuestionnaireItem(item_id="x", question="q", topic_tags=["access-control"])
        d = route_for_review(item, _CLEAR, ConfidenceResult(score=0.593), _policy())
        assert d.should_route is False
        assert d.reason_code is None

    def test_high_risk_tag_precedes_ungrounded(self):
        item = QuestionnaireItem(item_id="x", question="q", topic_tags=["legal"])
        d = route_for_review(item, _CLEAR, ConfidenceResult(score=0.593), _policy(), grounded=False)
        assert d.reason_code == ROUTED_HIGH_RISK
        assert d.queue == "legal"

    def test_low_confidence_precedes_ungrounded(self):
        item = QuestionnaireItem(item_id="x", question="q", topic_tags=["access-control"])
        d = route_for_review(item, _CLEAR, ConfidenceResult(score=0.10), _policy(), grounded=False)
        assert d.reason_code == ROUTED_LOW_CONFIDENCE

    def test_sensitivity_precedes_ungrounded(self):
        item = QuestionnaireItem(item_id="x", question="q", topic_tags=["access-control"])
        chunks = [_chunk("c1", "alpha", bm25=5.0, sensitivity="internal"),
                  _chunk("c2", "beta", bm25=1.0)]
        d = route_for_review(item, chunks, ConfidenceResult(score=0.593), _policy(), grounded=False)
        assert d.reason_code == ROUTED_SENSITIVE

    def test_bo035_shape_now_routes(self):
        # BO-035 reproduction: public, access-control (not high-risk), conf 0.593, public chunks, ungrounded
        item = QuestionnaireItem(item_id="BO-035", question="MFA TOTP FIDO2 WebAuthn", topic_tags=["access-control"])
        d = route_for_review(item, _CLEAR, ConfidenceResult(score=0.593), _policy(), grounded=False)
        assert d.should_route is True
        assert d.reason_code == ROUTED_UNGROUNDED


# --------------------------------------------------------------------------- PR-2
_CHUNK_TEXT = "We encrypt customer data at rest using AES-256 encryption keys"


def _ctx(retrieval):
    return ContextStack(instruction="i", retrieval=retrieval, constraint="c", state="s")


def _grounded_draft():
    # text == chunk text → content coverage 1.0 (conditions 1–3 pass); the variable is condition 4
    return DraftAnswer(text=_CHUNK_TEXT, citations=[Citation(chunk_id="c1")])


class TestPR2ContentlessQuestion:
    def test_contentless_question_fails_closed(self):
        ctx = _ctx([f"[c1] {_CHUNK_TEXT}"])
        r = grounding_check(_grounded_draft(), ctx, question="What about it?")
        assert r.grounded is False
        assert r.reason_code == GROUNDING_FAIL
        assert r.answer.text == UNGROUNDED_PLACEHOLDER  # byte-exact

    def test_single_token_question_unaffected(self):
        # "Encryption." → 1 significant token, present in the chunk → PR-2 does NOT fire → grounded
        ctx = _ctx([f"[c1] {_CHUNK_TEXT}"])
        r = grounding_check(_grounded_draft(), ctx, question="Encryption.")
        assert r.grounded is True

    def test_question_none_unchanged(self):
        # legacy callers pass question=None → condition 4 skipped entirely (backward-compatible)
        ctx = _ctx([f"[c1] {_CHUNK_TEXT}"])
        r = grounding_check(_grounded_draft(), ctx, question=None)
        assert r.grounded is True

    def test_real_question_still_grounds(self):
        ctx = _ctx([f"[c1] {_CHUNK_TEXT}"])
        r = grounding_check(_grounded_draft(), ctx, question="How do you encrypt customer data at rest?")
        assert r.grounded is True
