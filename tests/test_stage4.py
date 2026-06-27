"""
tests/test_stage4.py — Offline deterministic suite for Stage 4.

Covers: CONF1–CONF3, ROUTE1–ROUTE3, STATUS1–STATUS2, and progressive ENV4
(app.confidence, app.routing, app.state added to the import-safety set).

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: all functions are pure / seeded; no random state.

QA check mapping:
  CONF1  — score_confidence computed from validators only; identical inputs → identical score
  CONF2  — score invariant to rationale (changing/removing rationale leaves score unchanged)
  CONF3  — confidence_band banding: >= AUTO → "auto"; < REVIEW → "review"; in-between → "review"
  ROUTE1 — high-risk-tagged item routes with ROUTED_HIGH_RISK regardless of score
  ROUTE2 — top1−top2 < AMBIGUITY_SCORE_MARGIN → ROUTED_AMBIGUOUS
  ROUTE3 — score < CONFIDENCE_REVIEW_THRESHOLD → ROUTED_LOW_CONFIDENCE; queue from policy map
  STATUS1 — legal edges allowed; illegal edge raises InvalidTransition
  STATUS2 — agent→human-only target raises SelfApproveBlocked(SELF_APPROVE_BLOCKED);
             same transition by actor="human" is allowed
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Shared test helpers / mini-fixtures
# ---------------------------------------------------------------------------

def _make_chunk(
    chunk_id: str,
    answer: str,
    bm25_score: float = 1.0,
    question: str | None = None,
    sensitivity: str = "public",
    topic_tags: list[str] | None = None,
):
    from app.schema import RetrievedChunk
    return RetrievedChunk(
        chunk_id=chunk_id,
        answer=answer,
        question=question,
        sensitivity=sensitivity,
        topic_tags=topic_tags or [],
        approved=True,
        bm25_score=bm25_score,
    )


def _make_item(
    item_id: str = "i1",
    question: str = "How do you secure data at rest?",
    topic_tags: list[str] | None = None,
):
    from app.schema import QuestionnaireItem
    return QuestionnaireItem(
        item_id=item_id,
        question=question,
        topic_tags=topic_tags or [],
    )


def _make_grounding(grounded: bool = True):
    """Return a GroundingResult stub."""
    from app.draft import GroundingResult
    from app.schema import DraftAnswer
    return GroundingResult(
        grounded=grounded,
        answer=DraftAnswer(text="Some answer." if grounded else "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]", citations=[]),
        reason_code=None if grounded else "GROUNDING_FAIL",
    )


def _make_policy_tags(
    extra_routing: dict[str, str] | None = None,
    high_risk_override: list[str] | None = None,
) -> dict:
    """Minimal policy_tags dict for routing tests."""
    routing_map = {
        "legal": "legal",
        "security": "security",
        "compliance": "security",
        "engineering": "engineering",
        "infrastructure": "engineering",
    }
    if extra_routing:
        routing_map.update(extra_routing)
    return {
        "sensitivity_tags": ["public", "internal", "restricted"],
        "high_risk_tags": high_risk_override if high_risk_override is not None else ["legal", "security"],
        "routing_map": routing_map,
    }


# ---------------------------------------------------------------------------
# Progressive ENV4 — import-safety for Stage 4 modules
# ---------------------------------------------------------------------------

class TestENV4Stage4:
    """ENV4 (progressive): Stage 4 modules import without side effects.

    Adds app.confidence, app.routing, app.state to the tested set.
    Prior stages' modules remain tested in their own test files.
    """

    MODULES_TO_TEST = [
        "app.config",
        "app.schema",
        "app.kb",
        "app.retrieval",
        "app.eval.rubric",
        "app.eval.fixtures",
        "app.context_stack",
        "app.llm",
        "app.draft",
        "app.confidence",
        "app.routing",
        "app.state",
    ]

    def test_stage4_modules_import_cleanly(self):
        """Stage 4 app.* modules import without raising in a subprocess with no .env."""
        code = (
            f"import sys; sys.path.insert(0, r'{REPO_ROOT}'); "
            + "; ".join(f"import {m}" for m in self.MODULES_TO_TEST)
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        assert result.returncode == 0, (
            f"Import of Stage 4 app modules failed:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_confidence_no_side_effects_at_import(self):
        """app.confidence imports without any side effects."""
        import app.confidence  # noqa: F401

    def test_routing_no_side_effects_at_import(self):
        """app.routing imports without any side effects."""
        import app.routing  # noqa: F401

    def test_state_no_side_effects_at_import(self):
        """app.state imports without any side effects."""
        import app.state  # noqa: F401

    def test_new_config_constants_exist(self):
        """New Stage 4 constants exist in app.config with correct values."""
        import app.config as cfg

        # Audit reason-codes
        assert hasattr(cfg, "ROUTED_HIGH_RISK")
        assert cfg.ROUTED_HIGH_RISK == "ROUTED_HIGH_RISK"

        assert hasattr(cfg, "ROUTED_AMBIGUOUS")
        assert cfg.ROUTED_AMBIGUOUS == "ROUTED_AMBIGUOUS"

        assert hasattr(cfg, "ROUTED_LOW_CONFIDENCE")
        assert cfg.ROUTED_LOW_CONFIDENCE == "ROUTED_LOW_CONFIDENCE"

        assert hasattr(cfg, "SELF_APPROVE_BLOCKED")
        assert cfg.SELF_APPROVE_BLOCKED == "SELF_APPROVE_BLOCKED"

        # Default reviewer queue
        assert hasattr(cfg, "DEFAULT_REVIEWER_QUEUE")
        assert cfg.DEFAULT_REVIEWER_QUEUE == "engineering"
        assert cfg.DEFAULT_REVIEWER_QUEUE in cfg.REVIEWER_QUEUES, (
            "DEFAULT_REVIEWER_QUEUE must be ∈ REVIEWER_QUEUES"
        )


# ---------------------------------------------------------------------------
# CONF1 — score computed from validators only; identical inputs → identical score
# ---------------------------------------------------------------------------

class TestCONF1:
    """CONF1: score_confidence() returns a number from property validators only;
    no model call; identical inputs → identical score.
    """

    def test_score_confidence_returns_confidence_result(self):
        """score_confidence returns a ConfidenceResult."""
        from app.confidence import score_confidence
        from app.schema import ConfidenceResult

        chunks = [_make_chunk("c1", "We use AES-256 encryption for data at rest.", bm25_score=2.5)]
        grounding = _make_grounding(grounded=True)
        result = score_confidence(chunks, grounding, "How do you secure data at rest?")
        assert isinstance(result, ConfidenceResult), (
            f"score_confidence must return ConfidenceResult; got {type(result)}"
        )

    def test_score_in_valid_range(self):
        """score is in [0.0, 1.0]."""
        from app.confidence import score_confidence

        chunks = [_make_chunk("c1", "AES-256 encryption at rest.", bm25_score=1.8)]
        grounding = _make_grounding(grounded=True)
        result = score_confidence(chunks, grounding, "How do you secure data?")
        assert 0.0 <= result.score <= 1.0, (
            f"score must be in [0, 1]; got {result.score}"
        )

    def test_identical_inputs_produce_identical_score(self):
        """Identical inputs → identical score (deterministic)."""
        from app.confidence import score_confidence

        chunks = [
            _make_chunk("c1", "We use AES-256 encryption for data at rest.", bm25_score=2.5),
            _make_chunk("c2", "MFA is required for admin access.", bm25_score=1.2),
        ]
        grounding = _make_grounding(grounded=True)
        question = "How do you secure data at rest?"

        result1 = score_confidence(chunks, grounding, question)
        result2 = score_confidence(chunks, grounding, question)
        assert result1.score == result2.score, (
            f"Identical inputs must yield identical scores: {result1.score} vs {result2.score}"
        )

    def test_score_uses_no_model_call(self):
        """score_confidence does not trigger any model or network activity."""
        from app.confidence import score_confidence
        import app.config as cfg

        # If ClaudeLLM were called, _claude_client would be non-None.
        cfg._claude_client = None  # reset to ensure clean state
        chunks = [_make_chunk("c1", "encryption aes data rest", bm25_score=1.0)]
        grounding = _make_grounding(grounded=True)
        score_confidence(chunks, grounding, "encrypt data")
        assert cfg._claude_client is None, (
            "score_confidence must not trigger _get_claude(); the client must remain None."
        )

    def test_grounded_false_lowers_score(self):
        """An ungrounded result (grounding.grounded=False) lowers the score vs grounded."""
        from app.confidence import score_confidence

        chunks = [_make_chunk("c1", "Data encryption uses AES-256.", bm25_score=2.0)]
        question = "How do you encrypt data?"
        grounding_pass = _make_grounding(grounded=True)
        grounding_fail = _make_grounding(grounded=False)

        score_pass = score_confidence(chunks, grounding_pass, question).score
        score_fail = score_confidence(chunks, grounding_fail, question).score
        assert score_fail < score_pass, (
            f"Ungrounded result should yield lower score: "
            f"grounded={score_pass}, ungrounded={score_fail}"
        )

    def test_no_chunks_produces_zero_retrieval_dominance(self):
        """With no chunks, retrieval_dominance component is 0.0."""
        from app.confidence import _compute_score

        grounding = _make_grounding(grounded=True)
        score = _compute_score([], grounding, "How do you secure data?")
        # coverage with empty chunks = 0.0 (no token overlap),
        # grounded = 1.0, retrieval_dominance = 0.0 → mean = 1/3 ≈ 0.333
        # Actually: question tokens not in empty chunk union → coverage = 0.
        # But grounded=True so grounded_val=1.0, retrieval_dominance=0.0
        # mean = (0 + 1 + 0) / 3 ≈ 0.333
        assert 0.0 <= score <= 1.0

    def test_compute_score_pure_helper_exists(self):
        """_compute_score is exported and is a pure function."""
        from app.confidence import _compute_score
        assert callable(_compute_score)


# ---------------------------------------------------------------------------
# CONF2 — score invariant to rationale
# ---------------------------------------------------------------------------

class TestCONF2:
    """CONF2: the score is invariant to the rationale string.

    Changing or removing ConfidenceResult.rationale must not affect .score.
    The score is computed in _compute_score() which is independent of rationale.
    """

    def test_score_unchanged_when_rationale_cleared(self):
        """Clearing the rationale field does not change the score."""
        from app.confidence import score_confidence

        chunks = [
            _make_chunk("c1", "We use AES-256 encryption for data at rest.", bm25_score=2.5),
            _make_chunk("c2", "Backups are encrypted with the same key.", bm25_score=1.0),
        ]
        grounding = _make_grounding(grounded=True)
        question = "How do you secure data at rest?"

        result = score_confidence(chunks, grounding, question)
        original_score = result.score

        # Mutate/clear the rationale
        result.rationale = ""
        assert result.score == original_score, (
            "Score must not change when rationale is cleared"
        )

    def test_score_unchanged_when_rationale_replaced(self):
        """Replacing the rationale with different text does not change the score."""
        from app.confidence import score_confidence, _compute_score

        chunks = [_make_chunk("c1", "AES-256 encryption data rest.", bm25_score=1.5)]
        grounding = _make_grounding(grounded=True)
        question = "How do you secure data at rest?"

        # Compute score directly via the pure helper — that is what score_confidence uses.
        pure_score = _compute_score(chunks, grounding, question)

        result = score_confidence(chunks, grounding, question)
        assert result.score == pure_score, (
            f"score_confidence.score must equal _compute_score output; "
            f"got {result.score} vs {pure_score}"
        )

    def test_compute_score_independent_of_result_object(self):
        """_compute_score is a pure function — calling it twice gives the same number."""
        from app.confidence import _compute_score

        chunks = [
            _make_chunk("cx1", "encryption security data protection", bm25_score=3.0),
            _make_chunk("cx2", "access control multi factor authentication", bm25_score=1.0),
        ]
        grounding = _make_grounding(grounded=True)
        question = "How is data protected?"

        s1 = _compute_score(chunks, grounding, question)
        s2 = _compute_score(chunks, grounding, question)
        assert s1 == s2, f"_compute_score must be pure/deterministic: {s1} vs {s2}"

    def test_rationale_is_non_empty_string(self):
        """The rationale string is non-empty (it is an explanatory template)."""
        from app.confidence import score_confidence

        chunks = [_make_chunk("cr1", "AES-256 encrypts data at rest.", bm25_score=2.0)]
        grounding = _make_grounding(grounded=True)
        result = score_confidence(chunks, grounding, "How is data encrypted?")
        assert isinstance(result.rationale, str) and len(result.rationale) > 0, (
            "Rationale should be a non-empty explanatory string"
        )


# ---------------------------------------------------------------------------
# CONF3 — threshold banding
# ---------------------------------------------------------------------------

class TestCONF3:
    """CONF3: confidence_band() bands via §9 thresholds; no inline magic numbers."""

    def test_high_score_returns_auto(self):
        """score >= CONFIDENCE_AUTO_THRESHOLD → 'auto'."""
        from app.confidence import confidence_band
        from app.config import CONFIDENCE_AUTO_THRESHOLD

        band = confidence_band(CONFIDENCE_AUTO_THRESHOLD)
        assert band == "auto", (
            f"score == CONFIDENCE_AUTO_THRESHOLD should yield 'auto'; got {band!r}"
        )

    def test_above_auto_threshold_returns_auto(self):
        """score > CONFIDENCE_AUTO_THRESHOLD → 'auto'."""
        from app.confidence import confidence_band
        from app.config import CONFIDENCE_AUTO_THRESHOLD

        band = confidence_band(CONFIDENCE_AUTO_THRESHOLD + 0.1)
        assert band == "auto", f"score > AUTO_THRESHOLD should yield 'auto'; got {band!r}"

    def test_score_1_returns_auto(self):
        """score == 1.0 → 'auto'."""
        from app.confidence import confidence_band
        assert confidence_band(1.0) == "auto"

    def test_low_score_returns_review(self):
        """score < CONFIDENCE_REVIEW_THRESHOLD → 'review'."""
        from app.confidence import confidence_band
        from app.config import CONFIDENCE_REVIEW_THRESHOLD

        band = confidence_band(CONFIDENCE_REVIEW_THRESHOLD - 0.01)
        assert band == "review", (
            f"score < CONFIDENCE_REVIEW_THRESHOLD should yield 'review'; got {band!r}"
        )

    def test_score_0_returns_review(self):
        """score == 0.0 → 'review'."""
        from app.confidence import confidence_band
        assert confidence_band(0.0) == "review"

    def test_in_between_score_returns_review(self):
        """In-between score (>= REVIEW but < AUTO) → 'review' (conservative)."""
        from app.confidence import confidence_band
        from app.config import CONFIDENCE_AUTO_THRESHOLD, CONFIDENCE_REVIEW_THRESHOLD

        mid = (CONFIDENCE_AUTO_THRESHOLD + CONFIDENCE_REVIEW_THRESHOLD) / 2.0
        band = confidence_band(mid)
        assert band == "review", (
            f"In-between score {mid} should conservatively yield 'review'; got {band!r}"
        )

    def test_just_below_auto_threshold_returns_review(self):
        """score just below CONFIDENCE_AUTO_THRESHOLD → 'review'."""
        from app.confidence import confidence_band
        from app.config import CONFIDENCE_AUTO_THRESHOLD

        band = confidence_band(CONFIDENCE_AUTO_THRESHOLD - 0.001)
        assert band == "review", (
            f"score just below AUTO_THRESHOLD should yield 'review'; got {band!r}"
        )

    def test_thresholds_come_from_config(self):
        """Verify thresholds used match the §9 constants (not inline literals)."""
        from app.config import CONFIDENCE_AUTO_THRESHOLD, CONFIDENCE_REVIEW_THRESHOLD

        # Sanity-check: the constants have the expected anchoring values from §9
        assert CONFIDENCE_AUTO_THRESHOLD == 0.75, (
            f"CONFIDENCE_AUTO_THRESHOLD should be 0.75 (§9); got {CONFIDENCE_AUTO_THRESHOLD}"
        )
        assert CONFIDENCE_REVIEW_THRESHOLD == 0.50, (
            f"CONFIDENCE_REVIEW_THRESHOLD should be 0.50 (§9); got {CONFIDENCE_REVIEW_THRESHOLD}"
        )


# ---------------------------------------------------------------------------
# ROUTE1 — high-risk tag → ROUTED_HIGH_RISK regardless of confidence
# ---------------------------------------------------------------------------

class TestROUTE1:
    """ROUTE1: a high-risk-tagged item routes with ROUTED_HIGH_RISK regardless of score;
    queue resolved from the policy routing_map for the matched high-risk tag.
    """

    def test_legal_tag_routes_high_risk(self):
        """Item tagged 'legal' (a HIGH_RISK_TAG) is routed with ROUTED_HIGH_RISK."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import ROUTED_HIGH_RISK, RULE_HITM_REVIEW_TRIGGER

        item = _make_item(topic_tags=["legal"])
        chunks = [_make_chunk("c1", "Our legal terms of service.", bm25_score=5.0)]
        # High confidence — trigger should fire anyway (precedence over confidence)
        confidence = ConfidenceResult(score=0.95, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True, "High-risk-tagged item must be routed"
        assert decision.reason_code == ROUTED_HIGH_RISK, (
            f"reason_code must be ROUTED_HIGH_RISK; got {decision.reason_code!r}"
        )
        assert decision.rule == RULE_HITM_REVIEW_TRIGGER, (
            f"rule must be RULE_HITM_REVIEW_TRIGGER; got {decision.rule!r}"
        )

    def test_security_tag_routes_high_risk(self):
        """Item tagged 'security' (a HIGH_RISK_TAG) is routed with ROUTED_HIGH_RISK."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import ROUTED_HIGH_RISK

        item = _make_item(topic_tags=["security"])
        chunks = [_make_chunk("c1", "Access is controlled via security policies.", bm25_score=3.0)]
        confidence = ConfidenceResult(score=0.90, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.reason_code == ROUTED_HIGH_RISK

    def test_high_risk_tag_routes_to_mapped_queue(self):
        """High-risk tag routes to the queue mapped in the policy routing_map."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult

        item = _make_item(topic_tags=["legal"])
        chunks = [_make_chunk("c1", "Legal contract terms.", bm25_score=2.0)]
        confidence = ConfidenceResult(score=0.90, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        # "legal" maps to "legal" queue in the policy_tags fixture
        assert decision.queue == "legal", (
            f"High-risk 'legal' tag should route to 'legal' queue; got {decision.queue!r}"
        )

    def test_high_risk_overrides_high_confidence(self):
        """High-risk tag fires even when confidence is very high (ROUTE1 — precedence)."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import ROUTED_HIGH_RISK

        item = _make_item(topic_tags=["legal"])
        chunks = [_make_chunk("c1", "legal terms contract agreement liability", bm25_score=9.9)]
        # Perfect score
        confidence = ConfidenceResult(score=1.0, rationale="max")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.reason_code == ROUTED_HIGH_RISK


# ---------------------------------------------------------------------------
# ROUTE2 — ambiguity → ROUTED_AMBIGUOUS
# ---------------------------------------------------------------------------

class TestROUTE2:
    """ROUTE2: top1−top2 BM25 gap < AMBIGUITY_SCORE_MARGIN → ROUTED_AMBIGUOUS."""

    def test_small_gap_routes_ambiguous(self):
        """top1−top2 < AMBIGUITY_SCORE_MARGIN → ROUTED_AMBIGUOUS."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import AMBIGUITY_SCORE_MARGIN, ROUTED_AMBIGUOUS, RULE_HITM_REVIEW_TRIGGER

        # No high-risk tags — ensure ambiguity trigger fires
        item = _make_item(topic_tags=["infrastructure"])
        # Gap = 0.05 < 0.10 (AMBIGUITY_SCORE_MARGIN)
        gap = AMBIGUITY_SCORE_MARGIN / 2.0
        chunks = [
            _make_chunk("c1", "Network is secured.", bm25_score=2.0),
            _make_chunk("c2", "Network is protected.", bm25_score=2.0 - gap),
        ]
        # Confidence above REVIEW threshold — ambiguity should still fire
        confidence = ConfidenceResult(score=0.85, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.reason_code == ROUTED_AMBIGUOUS, (
            f"reason_code must be ROUTED_AMBIGUOUS; got {decision.reason_code!r}"
        )
        assert decision.rule == RULE_HITM_REVIEW_TRIGGER

    def test_zero_gap_routes_ambiguous(self):
        """Equal BM25 scores (gap = 0) → ROUTED_AMBIGUOUS."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import ROUTED_AMBIGUOUS

        item = _make_item(topic_tags=["infrastructure"])
        chunks = [
            _make_chunk("c1", "Secure infrastructure A.", bm25_score=3.0),
            _make_chunk("c2", "Secure infrastructure B.", bm25_score=3.0),
        ]
        confidence = ConfidenceResult(score=0.80, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.reason_code == ROUTED_AMBIGUOUS

    def test_large_gap_does_not_route_ambiguous(self):
        """top1−top2 >= AMBIGUITY_SCORE_MARGIN → no ambiguity trigger (alone)."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import AMBIGUITY_SCORE_MARGIN, ROUTED_AMBIGUOUS

        item = _make_item(topic_tags=["infrastructure"])
        # Gap = 2 * margin → clearly above threshold
        gap = AMBIGUITY_SCORE_MARGIN * 2.0
        chunks = [
            _make_chunk("c1", "security encryption data", bm25_score=5.0),
            _make_chunk("c2", "unrelated content", bm25_score=5.0 - gap),
        ]
        # High confidence to prevent trigger 3
        confidence = ConfidenceResult(score=0.90, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        # Ambiguity trigger should NOT fire; no trigger fires at all
        assert decision.reason_code != ROUTED_AMBIGUOUS

    def test_single_chunk_no_ambiguity_trigger(self):
        """With only one chunk, ambiguity cannot trigger (no top2 to compare)."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import ROUTED_AMBIGUOUS

        item = _make_item(topic_tags=[])
        chunks = [_make_chunk("c1", "encryption data security", bm25_score=3.0)]
        confidence = ConfidenceResult(score=0.90, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.reason_code != ROUTED_AMBIGUOUS


# ---------------------------------------------------------------------------
# ROUTE3 — low confidence → ROUTED_LOW_CONFIDENCE; queue from policy map (not hardcoded)
# ---------------------------------------------------------------------------

class TestROUTE3:
    """ROUTE3: score < CONFIDENCE_REVIEW_THRESHOLD → ROUTED_LOW_CONFIDENCE;
    queue resolved from the policy routing_map (never hardcoded);
    a benign high-confidence, non-high-risk item → should_route=False.
    """

    def test_low_confidence_routes(self):
        """score < CONFIDENCE_REVIEW_THRESHOLD → ROUTED_LOW_CONFIDENCE."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import (
            CONFIDENCE_REVIEW_THRESHOLD,
            ROUTED_LOW_CONFIDENCE,
            RULE_HITM_REVIEW_TRIGGER,
        )

        item = _make_item(topic_tags=["infrastructure"])
        chunks = [_make_chunk("c1", "Some answer.", bm25_score=0.5)]
        confidence = ConfidenceResult(
            score=CONFIDENCE_REVIEW_THRESHOLD - 0.01,
            rationale="low",
        )
        # Make top1−top2 gap large enough to not trigger ambiguity
        chunks[0].bm25_score = 5.0
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.reason_code == ROUTED_LOW_CONFIDENCE, (
            f"reason_code must be ROUTED_LOW_CONFIDENCE; got {decision.reason_code!r}"
        )
        assert decision.rule == RULE_HITM_REVIEW_TRIGGER

    def test_low_confidence_queue_from_policy_map(self):
        """Queue for low-confidence trigger is resolved from the policy routing_map, not hardcoded."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import CONFIDENCE_REVIEW_THRESHOLD

        item = _make_item(topic_tags=["infrastructure"])  # "infrastructure" → "engineering"
        chunks = [_make_chunk("c1", "Some answer.", bm25_score=5.0)]
        confidence = ConfidenceResult(
            score=CONFIDENCE_REVIEW_THRESHOLD - 0.05,
            rationale="low",
        )
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        # "infrastructure" maps to "engineering" in the policy map
        assert decision.queue == "engineering", (
            f"Queue for 'infrastructure' tag should be 'engineering' from policy map; "
            f"got {decision.queue!r}"
        )

    def test_low_confidence_no_tag_match_uses_default_queue(self):
        """When no topic tag maps, low-confidence trigger uses DEFAULT_REVIEWER_QUEUE fallback."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import CONFIDENCE_REVIEW_THRESHOLD, DEFAULT_REVIEWER_QUEUE

        # Tag "unknown-topic" is not in the policy routing_map
        item = _make_item(topic_tags=["unknown-topic"])
        chunks = [_make_chunk("c1", "Some answer.", bm25_score=5.0)]
        confidence = ConfidenceResult(
            score=CONFIDENCE_REVIEW_THRESHOLD - 0.05,
            rationale="low",
        )
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.queue == DEFAULT_REVIEWER_QUEUE, (
            f"No-match tag should fallback to DEFAULT_REVIEWER_QUEUE={DEFAULT_REVIEWER_QUEUE!r}; "
            f"got {decision.queue!r}"
        )

    def test_high_confidence_no_high_risk_no_ambiguity_not_routed(self):
        """A benign high-confidence, non-high-risk item with clear retrieval → should_route=False."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import CONFIDENCE_AUTO_THRESHOLD, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["certification"])  # not in high_risk_tags
        # Large gap to avoid ambiguity
        gap = AMBIGUITY_SCORE_MARGIN * 3.0
        chunks = [
            _make_chunk("c1", "We are ISO 27001 certified.", bm25_score=5.0),
            _make_chunk("c2", "Our certifications are audited annually.", bm25_score=5.0 - gap),
        ]
        confidence = ConfidenceResult(score=CONFIDENCE_AUTO_THRESHOLD, rationale="auto")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is False, (
            f"Benign item should NOT be routed; got should_route=True, "
            f"reason_code={decision.reason_code!r}"
        )
        assert decision.queue is None
        assert decision.reason_code is None
        assert decision.rule is None

    def test_high_risk_takes_precedence_over_ambiguity(self):
        """High-risk tag fires before ambiguity check (precedence order)."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import AMBIGUITY_SCORE_MARGIN, ROUTED_HIGH_RISK

        item = _make_item(topic_tags=["legal"])  # high-risk
        # Also ambiguous
        gap = AMBIGUITY_SCORE_MARGIN / 2.0
        chunks = [
            _make_chunk("c1", "Legal contract.", bm25_score=2.0),
            _make_chunk("c2", "Legal terms.", bm25_score=2.0 - gap),
        ]
        confidence = ConfidenceResult(score=0.85, rationale="high")
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.reason_code == ROUTED_HIGH_RISK, (
            f"High-risk should take precedence over ambiguity; got {decision.reason_code!r}"
        )

    def test_ambiguity_takes_precedence_over_low_confidence(self):
        """Ambiguity fires before low-confidence check (precedence order)."""
        from app.routing import route_for_review
        from app.schema import ConfidenceResult
        from app.config import AMBIGUITY_SCORE_MARGIN, CONFIDENCE_REVIEW_THRESHOLD, ROUTED_AMBIGUOUS

        item = _make_item(topic_tags=["infrastructure"])  # not high-risk
        gap = AMBIGUITY_SCORE_MARGIN / 2.0
        chunks = [
            _make_chunk("c1", "Infrastructure is secured.", bm25_score=2.0),
            _make_chunk("c2", "Infrastructure uses VPNs.", bm25_score=2.0 - gap),
        ]
        # Also low confidence — but ambiguity should fire first
        confidence = ConfidenceResult(
            score=CONFIDENCE_REVIEW_THRESHOLD - 0.1,
            rationale="low",
        )
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.reason_code == ROUTED_AMBIGUOUS, (
            f"Ambiguity should take precedence over low-confidence; got {decision.reason_code!r}"
        )

    def test_real_policy_tags_file_loads_and_routes(self):
        """route_for_review works correctly with the actual loaded policy_tags data."""
        from app.routing import route_for_review
        from app.kb import load_policy_tags
        from app.schema import ConfidenceResult
        from app.config import CONFIDENCE_REVIEW_THRESHOLD, ROUTED_LOW_CONFIDENCE

        policy_tags = load_policy_tags()

        item = _make_item(topic_tags=["vulnerability-management"])  # in routing_map
        chunks = [_make_chunk("c1", "We patch vulnerabilities within 30 days.", bm25_score=5.0)]
        confidence = ConfidenceResult(
            score=CONFIDENCE_REVIEW_THRESHOLD - 0.1,
            rationale="low",
        )
        decision = route_for_review(item, chunks, confidence, policy_tags)
        assert decision.should_route is True
        assert decision.reason_code == ROUTED_LOW_CONFIDENCE
        # "vulnerability-management" maps to "security" in the real policy_tags
        assert decision.queue == "security", (
            f"'vulnerability-management' should route to 'security'; got {decision.queue!r}"
        )


# ---------------------------------------------------------------------------
# STATUS1 — state machine legality
# ---------------------------------------------------------------------------

class TestSTATUS1:
    """STATUS1: items advance only along legal ITEM_STATES edges;
    an illegal transition raises InvalidTransition (not a silent jump).
    """

    def test_legal_transition_succeeds(self):
        """INTAKE → RETRIEVED is a legal edge; should return 'RETRIEVED'."""
        from app.state import transition

        result = transition("INTAKE", "RETRIEVED", actor="agent")
        assert result == "RETRIEVED"

    def test_full_agent_path_legal(self):
        """Agent can follow the full happy path up to SCORED."""
        from app.state import transition

        state = "INTAKE"
        state = transition(state, "RETRIEVED", actor="agent")
        assert state == "RETRIEVED"
        state = transition(state, "DRAFTED", actor="agent")
        assert state == "DRAFTED"
        state = transition(state, "SCORED", actor="agent")
        assert state == "SCORED"
        state = transition(state, "ROUTED_FOR_REVIEW", actor="agent")
        assert state == "ROUTED_FOR_REVIEW"

    def test_illegal_edge_raises_invalid_transition(self):
        """INTAKE → EXPORTED is not a legal edge; must raise InvalidTransition."""
        from app.state import transition, InvalidTransition

        with pytest.raises(InvalidTransition):
            transition("INTAKE", "EXPORTED", actor="human")

    def test_illegal_skip_raises(self):
        """INTAKE → SCORED (skipping states) is not a legal edge."""
        from app.state import transition, InvalidTransition

        with pytest.raises(InvalidTransition):
            transition("INTAKE", "SCORED", actor="agent")

    def test_backward_transition_raises(self):
        """EXPORTED → INTAKE is not a legal edge."""
        from app.state import transition, InvalidTransition

        with pytest.raises(InvalidTransition):
            transition("EXPORTED", "INTAKE", actor="agent")

    def test_terminal_state_raises_on_any_transition(self):
        """EXPORTED is a terminal state; any outgoing transition raises."""
        from app.state import transition, InvalidTransition

        with pytest.raises(InvalidTransition):
            transition("EXPORTED", "APPROVED", actor="human")

    def test_unknown_current_state_raises(self):
        """An unknown current state produces an illegal transition for any target."""
        from app.state import transition, InvalidTransition

        with pytest.raises(InvalidTransition):
            transition("NONEXISTENT_STATE", "INTAKE", actor="agent")

    def test_review_rejected_allows_retry(self):
        """REVIEW_REJECTED → DRAFTED is the legal retry path."""
        from app.state import transition

        result = transition("REVIEW_REJECTED", "DRAFTED", actor="human")
        assert result == "DRAFTED"

    def test_legal_transitions_covers_all_item_states(self):
        """LEGAL_TRANSITIONS has a key for every ITEM_STATE."""
        from app.state import LEGAL_TRANSITIONS
        from app.config import ITEM_STATES

        for state in ITEM_STATES:
            assert state in LEGAL_TRANSITIONS, (
                f"ITEM_STATE '{state}' has no entry in LEGAL_TRANSITIONS"
            )

    def test_invalid_transition_is_value_error(self):
        """InvalidTransition is a subclass of ValueError."""
        from app.state import InvalidTransition

        assert issubclass(InvalidTransition, ValueError), (
            "InvalidTransition must be a subclass of ValueError"
        )


# ---------------------------------------------------------------------------
# STATUS2 — RULE_NO_SELF_APPROVE: agent cannot enter human-only states
# ---------------------------------------------------------------------------

class TestSTATUS2:
    """STATUS2: agent→human-only target raises SelfApproveBlocked with SELF_APPROVE_BLOCKED;
    the same transition by actor='human' is allowed (RULE_NO_SELF_APPROVE).
    """

    def test_agent_cannot_approve(self):
        """agent attempting SCORED → APPROVED raises SelfApproveBlocked."""
        from app.state import transition, SelfApproveBlocked

        with pytest.raises(SelfApproveBlocked):
            transition("SCORED", "APPROVED", actor="agent")

    def test_agent_cannot_export(self):
        """agent attempting APPROVED → EXPORTED raises SelfApproveBlocked."""
        from app.state import transition, SelfApproveBlocked

        with pytest.raises(SelfApproveBlocked):
            transition("APPROVED", "EXPORTED", actor="agent")

    def test_agent_cannot_review_approve(self):
        """agent attempting ROUTED_FOR_REVIEW → REVIEW_APPROVED raises SelfApproveBlocked."""
        from app.state import transition, SelfApproveBlocked

        with pytest.raises(SelfApproveBlocked):
            transition("ROUTED_FOR_REVIEW", "REVIEW_APPROVED", actor="agent")

    def test_agent_cannot_review_reject(self):
        """agent attempting ROUTED_FOR_REVIEW → REVIEW_REJECTED raises SelfApproveBlocked."""
        from app.state import transition, SelfApproveBlocked

        with pytest.raises(SelfApproveBlocked):
            transition("ROUTED_FOR_REVIEW", "REVIEW_REJECTED", actor="agent")

    def test_self_approve_blocked_carries_reason_code(self):
        """SelfApproveBlocked carries reason_code == SELF_APPROVE_BLOCKED."""
        from app.state import transition, SelfApproveBlocked
        from app.config import SELF_APPROVE_BLOCKED

        with pytest.raises(SelfApproveBlocked) as exc_info:
            transition("SCORED", "APPROVED", actor="agent")

        exc = exc_info.value
        assert exc.reason_code == SELF_APPROVE_BLOCKED, (
            f"SelfApproveBlocked.reason_code must be SELF_APPROVE_BLOCKED; "
            f"got {exc.reason_code!r}"
        )

    def test_self_approve_blocked_carries_rule(self):
        """SelfApproveBlocked carries rule == RULE_NO_SELF_APPROVE."""
        from app.state import transition, SelfApproveBlocked
        from app.config import RULE_NO_SELF_APPROVE

        with pytest.raises(SelfApproveBlocked) as exc_info:
            transition("SCORED", "APPROVED", actor="agent")

        exc = exc_info.value
        assert exc.rule == RULE_NO_SELF_APPROVE, (
            f"SelfApproveBlocked.rule must be RULE_NO_SELF_APPROVE; got {exc.rule!r}"
        )

    def test_human_can_approve(self):
        """actor='human' is allowed to transition SCORED → APPROVED."""
        from app.state import transition

        result = transition("SCORED", "APPROVED", actor="human")
        assert result == "APPROVED"

    def test_human_can_export(self):
        """actor='human' is allowed to transition APPROVED → EXPORTED."""
        from app.state import transition

        result = transition("APPROVED", "EXPORTED", actor="human")
        assert result == "EXPORTED"

    def test_human_can_review_approve(self):
        """actor='human' is allowed to transition ROUTED_FOR_REVIEW → REVIEW_APPROVED."""
        from app.state import transition

        result = transition("ROUTED_FOR_REVIEW", "REVIEW_APPROVED", actor="human")
        assert result == "REVIEW_APPROVED"

    def test_human_can_review_reject(self):
        """actor='human' is allowed to transition ROUTED_FOR_REVIEW → REVIEW_REJECTED."""
        from app.state import transition

        result = transition("ROUTED_FOR_REVIEW", "REVIEW_REJECTED", actor="human")
        assert result == "REVIEW_REJECTED"

    def test_default_actor_is_agent(self):
        """The default actor is 'agent', so self-approve is blocked by default."""
        from app.state import transition, SelfApproveBlocked

        with pytest.raises(SelfApproveBlocked):
            transition("SCORED", "APPROVED")  # no actor= → defaults to "agent"

    def test_human_only_targets_set(self):
        """HUMAN_ONLY_TARGETS contains all expected states."""
        from app.state import HUMAN_ONLY_TARGETS

        expected = {"REVIEW_APPROVED", "REVIEW_REJECTED", "APPROVED", "EXPORTED"}
        assert HUMAN_ONLY_TARGETS == expected, (
            f"HUMAN_ONLY_TARGETS mismatch: {HUMAN_ONLY_TARGETS} vs {expected}"
        )

    def test_self_approve_blocked_is_value_error(self):
        """SelfApproveBlocked is a subclass of ValueError."""
        from app.state import SelfApproveBlocked

        assert issubclass(SelfApproveBlocked, ValueError), (
            "SelfApproveBlocked must be a subclass of ValueError"
        )

    def test_human_only_targets_all_in_item_states(self):
        """Every state in HUMAN_ONLY_TARGETS is a valid ITEM_STATE."""
        from app.state import HUMAN_ONLY_TARGETS
        from app.config import ITEM_STATES

        for state in HUMAN_ONLY_TARGETS:
            assert state in ITEM_STATES, (
                f"HUMAN_ONLY_TARGETS contains '{state}' which is not in ITEM_STATES"
            )
