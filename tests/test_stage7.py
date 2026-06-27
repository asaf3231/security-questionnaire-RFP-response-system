"""
tests/test_stage7.py — Offline deterministic suite for Stage 7.

Covers: EVAL1–EVAL3, LEAK4–LEAK5, sensitivity routing (ROUTE: Option-A trigger),
and progressive ENV4 (app.eval.harness added to the import-safety set).

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: computed metrics from held-out fixtures; no hardcoded scores.

QA check mapping:
  EVAL1  — all four metrics computed from labeled fixtures; no hardcoded values
  EVAL2  — held-out proof: contamination detected and rejected (RULE_NO_EVAL_CONTAMINATION)
  EVAL3  — calibration matrix is real (computed, not asserted)
  LEAK4  — = EVAL2 (contamination guard)
  LEAK5  — = EVAL1 (no fabricated metric)
  ROUTE (Option-A sensitivity trigger) — internal/restricted → compliance/ROUTED_SENSITIVE
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    chunk_id: str,
    answer: str,
    bm25_score: float = 1.0,
    sensitivity: str = "public",
    question: str | None = None,
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
    question: str = "How do you secure data?",
    topic_tags: list[str] | None = None,
):
    from app.schema import QuestionnaireItem
    return QuestionnaireItem(
        item_id=item_id,
        question=question,
        topic_tags=topic_tags or [],
    )


def _make_confidence(score: float = 0.85):
    from app.schema import ConfidenceResult
    return ConfidenceResult(score=score, rationale="test")


def _make_policy_tags(extra_routing: dict | None = None) -> dict:
    routing_map = {
        "legal": "legal",
        "security": "security",
        "compliance": "security",
        "infrastructure": "engineering",
    }
    if extra_routing:
        routing_map.update(extra_routing)
    return {
        "sensitivity_tags": ["public", "internal", "restricted"],
        "high_risk_tags": ["legal", "security"],
        "routing_map": routing_map,
    }


# ---------------------------------------------------------------------------
# Progressive ENV4 — import-safety for Stage 7 modules
# ---------------------------------------------------------------------------

class TestENV4Stage7:
    """ENV4 (progressive): Stage 7 modules import without side effects.

    Adds app.eval.harness to the tested import-safety set.
    """

    MODULES_TO_TEST = [
        "app.config",
        "app.schema",
        "app.kb",
        "app.retrieval",
        "app.context_stack",
        "app.llm",
        "app.draft",
        "app.confidence",
        "app.routing",
        "app.state",
        "app.audit",
        "app.export",
        "app.pipeline",
        "app.eval.harness",
    ]

    def test_eval_harness_imports_cleanly_subprocess(self):
        """ENV4: app.eval.harness imports without raising in a subprocess with no .env."""
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
            f"Import of Stage 7 app modules failed:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_eval_harness_import_no_side_effects(self):
        """ENV4: app.eval.harness imports in-process with zero side effects."""
        import app.eval.harness  # noqa: F401

    def test_run_eval_importable(self):
        """ENV4: run_eval() is importable from app.eval.harness."""
        from app.eval.harness import run_eval  # noqa: F401


# ---------------------------------------------------------------------------
# Option-A sensitivity routing — the 4th RULE_HITM_REVIEW_TRIGGER trigger
# ---------------------------------------------------------------------------

class TestSensitivityRouting:
    """New sensitivity routing trigger (Option-A, D-S7, ROUTE).

    The 4th trigger (lowest precedence): if any retrieved chunk has
    sensitivity ∈ {internal, restricted} and triggers 1-3 did not fire,
    route to SENSITIVITY_REVIEW_QUEUE ('compliance') with ROUTED_SENSITIVE.
    """

    def test_internal_chunk_triggers_sensitivity_route(self):
        """An item with only an internal chunk (no high-risk tag, high confidence, no ambiguity)
        routes to 'compliance' with ROUTED_SENSITIVE (Option-A, trigger 4)."""
        from app.routing import route_for_review
        from app.config import ROUTED_SENSITIVE, SENSITIVITY_REVIEW_QUEUE, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["infrastructure"])  # not a high-risk tag
        chunks = [
            _make_chunk("kb-int-1", "Data stored in US and EU regions.", sensitivity="internal",
                        bm25_score=5.0),
            _make_chunk("kb-pub-1", "Public docs available on request.", sensitivity="public",
                        bm25_score=5.0 - AMBIGUITY_SCORE_MARGIN * 3),  # clear gap → no ambiguity
        ]
        confidence = _make_confidence(score=0.85)  # high confidence → trigger 3 does not fire
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)

        assert decision.should_route is True, (
            "Internal chunk should trigger sensitivity routing"
        )
        assert decision.reason_code == ROUTED_SENSITIVE, (
            f"Expected ROUTED_SENSITIVE, got {decision.reason_code!r}"
        )
        assert decision.queue == SENSITIVITY_REVIEW_QUEUE, (
            f"Expected queue={SENSITIVITY_REVIEW_QUEUE!r}, got {decision.queue!r}"
        )
        from app.config import RULE_HITM_REVIEW_TRIGGER
        assert decision.rule == RULE_HITM_REVIEW_TRIGGER

    def test_restricted_chunk_triggers_sensitivity_route(self):
        """An item with a restricted chunk (no high-risk tag, high confidence, no ambiguity)
        routes via ROUTED_SENSITIVE."""
        from app.routing import route_for_review
        from app.config import ROUTED_SENSITIVE, SENSITIVITY_REVIEW_QUEUE, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["data-handling"])
        chunks = [
            _make_chunk("kb-res-1", "Coverage amounts disclosed under NDA.", sensitivity="restricted",
                        bm25_score=6.0),
            _make_chunk("kb-pub-2", "General info on our compliance posture.", sensitivity="public",
                        bm25_score=6.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.88)
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)

        assert decision.should_route is True
        assert decision.reason_code == ROUTED_SENSITIVE
        assert decision.queue == SENSITIVITY_REVIEW_QUEUE

    def test_public_chunks_only_not_sensitivity_routed(self):
        """An item with only public chunks is NOT routed by the sensitivity trigger."""
        from app.routing import route_for_review
        from app.config import AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["certification"])  # not a high-risk tag
        chunks = [
            _make_chunk("kb-pub-3", "We hold SOC 2 Type II certification.", sensitivity="public",
                        bm25_score=8.0),
            _make_chunk("kb-pub-4", "Annual audits by independent firm.", sensitivity="public",
                        bm25_score=8.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.90)
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)

        assert decision.should_route is False, (
            "Public-only chunks should NOT trigger sensitivity routing"
        )
        assert decision.reason_code is None
        assert decision.queue is None

    def test_high_risk_takes_precedence_over_sensitivity(self):
        """Trigger 1 (high-risk tag) fires before trigger 4 (sensitivity) — precedence."""
        from app.routing import route_for_review
        from app.config import ROUTED_HIGH_RISK, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["legal"])  # high-risk tag
        chunks = [
            _make_chunk("kb-leg-1", "Legal indemnification terms.", sensitivity="restricted",
                        bm25_score=5.0),
            _make_chunk("kb-pub-5", "General legal overview.", sensitivity="public",
                        bm25_score=5.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.88)
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)

        # Trigger 1 (high-risk) should fire, NOT trigger 4 (sensitivity)
        assert decision.reason_code == ROUTED_HIGH_RISK, (
            f"High-risk should take precedence over sensitivity; got {decision.reason_code!r}"
        )

    def test_low_confidence_takes_precedence_over_sensitivity(self):
        """Trigger 3 (low confidence) fires before trigger 4 (sensitivity) — precedence."""
        from app.routing import route_for_review
        from app.config import ROUTED_LOW_CONFIDENCE, CONFIDENCE_REVIEW_THRESHOLD, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["data-handling"])  # not high-risk
        chunks = [
            _make_chunk("kb-int-2", "Internal data handling procedures.", sensitivity="internal",
                        bm25_score=5.0),
            _make_chunk("kb-pub-6", "Public data overview.", sensitivity="public",
                        bm25_score=5.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        # Low confidence — trigger 3 should fire before trigger 4
        low_score = CONFIDENCE_REVIEW_THRESHOLD - 0.1
        confidence = _make_confidence(score=low_score)
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)

        assert decision.reason_code == ROUTED_LOW_CONFIDENCE, (
            f"Low confidence should take precedence over sensitivity; got {decision.reason_code!r}"
        )

    def test_sensitivity_routing_uses_sensitivity_review_queue_constant(self):
        """The sensitivity trigger routes to SENSITIVITY_REVIEW_QUEUE from config, not hardcoded."""
        from app.routing import route_for_review
        from app.config import SENSITIVITY_REVIEW_QUEUE, AMBIGUITY_SCORE_MARGIN

        item = _make_item(topic_tags=["data-handling"])
        chunks = [
            _make_chunk("kb-int-3", "Internal geographic data storage.", sensitivity="internal",
                        bm25_score=5.0),
            _make_chunk("kb-pub-7", "Public summary.", sensitivity="public",
                        bm25_score=5.0 - AMBIGUITY_SCORE_MARGIN * 3),
        ]
        confidence = _make_confidence(score=0.82)
        policy_tags = _make_policy_tags()

        decision = route_for_review(item, chunks, confidence, policy_tags)

        # Queue must match the §9 constant — never a hardcoded string
        assert decision.queue == SENSITIVITY_REVIEW_QUEUE
        assert SENSITIVITY_REVIEW_QUEUE in __import__("app.config", fromlist=["REVIEWER_QUEUES"]).REVIEWER_QUEUES, (
            "SENSITIVITY_REVIEW_QUEUE must be ∈ REVIEWER_QUEUES"
        )

    def test_routed_sensitive_constant_defined(self):
        """ROUTED_SENSITIVE is defined in app/config.py with correct value."""
        from app.config import ROUTED_SENSITIVE
        assert ROUTED_SENSITIVE == "ROUTED_SENSITIVE"

    def test_sensitivity_review_queue_in_reviewer_queues(self):
        """SENSITIVITY_REVIEW_QUEUE ('compliance') is ∈ REVIEWER_QUEUES."""
        from app.config import SENSITIVITY_REVIEW_QUEUE, REVIEWER_QUEUES
        assert SENSITIVITY_REVIEW_QUEUE in REVIEWER_QUEUES, (
            f"SENSITIVITY_REVIEW_QUEUE={SENSITIVITY_REVIEW_QUEUE!r} not in REVIEWER_QUEUES={REVIEWER_QUEUES}"
        )


# ---------------------------------------------------------------------------
# EVAL1 — All metrics computed from labeled fixtures (RULE_NO_FABRICATED_METRIC)
# ---------------------------------------------------------------------------

class TestEVAL1:
    """EVAL1: every metric is computed from labeled fixtures; no hardcoded value.

    RULE_NO_FABRICATED_METRIC: the metric values are derived from run_eval() applied
    to fixtures/eval/; tests assert the structure and validity of the return value,
    not specific numeric literals.
    """

    def test_run_eval_returns_all_required_metrics(self):
        """EVAL1: run_eval() returns a dict with all four required metric keys."""
        from app.eval.harness import run_eval

        result = run_eval()

        assert "recall_at_k" in result, "Missing recall_at_k in eval result"
        assert "grounding_rate" in result, "Missing grounding_rate in eval result"
        assert "routing_accuracy" in result, "Missing routing_accuracy in eval result"
        assert "calibration" in result, "Missing calibration in eval result"

    def test_recall_at_k_is_float_in_valid_range(self):
        """EVAL1: recall_at_k is a float in [0, 1] (computed, not hardcoded)."""
        from app.eval.harness import run_eval

        result = run_eval()

        recall = result["recall_at_k"]
        assert isinstance(recall, float), f"recall_at_k must be float, got {type(recall)}"
        assert 0.0 <= recall <= 1.0, f"recall_at_k must be in [0,1], got {recall}"

    def test_recall_at_k_meets_target(self):
        """EVAL1: computed Recall@K meets RECALL_AT_K_TARGET — proves it's meaningful."""
        from app.eval.harness import run_eval
        from app.config import RECALL_AT_K_TARGET

        result = run_eval()
        recall = result["recall_at_k"]

        assert recall >= RECALL_AT_K_TARGET, (
            f"Recall@K {recall:.4f} does not meet target {RECALL_AT_K_TARGET} "
            f"(RULE_NO_FABRICATED_METRIC: this is computed, not hardcoded)"
        )

    def test_grounding_rate_has_required_subkeys(self):
        """EVAL1: grounding_rate has match_rate and raw_grounded_rate subkeys."""
        from app.eval.harness import run_eval

        result = run_eval()
        gr = result["grounding_rate"]

        assert "match_rate" in gr
        assert "raw_grounded_rate" in gr
        assert 0.0 <= gr["match_rate"] <= 1.0
        assert 0.0 <= gr["raw_grounded_rate"] <= 1.0

    def test_routing_accuracy_is_float_in_valid_range(self):
        """EVAL1: routing_accuracy is a float in [0, 1] (computed, not hardcoded)."""
        from app.eval.harness import run_eval

        result = run_eval()

        acc = result["routing_accuracy"]
        assert isinstance(acc, float)
        assert 0.0 <= acc <= 1.0

    def test_calibration_matrix_structure(self):
        """EVAL1: calibration is a dict of band → {grounded: n, ungrounded: n} counts."""
        from app.eval.harness import run_eval

        result = run_eval()
        cal = result["calibration"]

        assert "auto" in cal and "review" in cal, (
            f"Calibration must have 'auto' and 'review' bands; got: {list(cal.keys())}"
        )
        for band_counts in cal.values():
            assert "grounded" in band_counts
            assert "ungrounded" in band_counts
            assert isinstance(band_counts["grounded"], int)
            assert isinstance(band_counts["ungrounded"], int)

    def test_calibration_total_equals_n_eval_cases(self):
        """EVAL1: sum of all calibration counts equals the number of eval cases."""
        from app.eval.harness import run_eval

        result = run_eval()
        n = result["n_eval_cases"]
        cal = result["calibration"]

        total = sum(
            counts["grounded"] + counts["ungrounded"]
            for counts in cal.values()
        )
        assert total == n, (
            f"Calibration total {total} != n_eval_cases {n} "
            f"(every case must be counted in exactly one band)"
        )

    def test_calibration_covers_both_bands(self):
        """EVAL1: the eval fixtures exercise both 'auto' and 'review' bands."""
        from app.eval.harness import run_eval

        result = run_eval()
        cal = result["calibration"]

        auto_total = cal["auto"]["grounded"] + cal["auto"]["ungrounded"]
        review_total = cal["review"]["grounded"] + cal["review"]["ungrounded"]
        assert auto_total > 0, "No eval case in the 'auto' confidence band — add more fixtures"
        assert review_total > 0, "No eval case in the 'review' confidence band — add more fixtures"

    def test_metrics_not_hardcoded_perturb_changes_result(self, tmp_path):
        """EVAL1 / LEAK5: metrics are computed — perturbing the fixture changes the result."""
        import json
        from app.eval.harness import run_eval, _load_eval_cases, _fixtures_dir

        # Run once to get baseline
        baseline = run_eval()

        # Copy the recall_at_k_gold.json into tmp_path (needed by _load_recall_gold).
        # Use pathlib read/write bytes to avoid importing shutil (not in STDLIB set for ENV2).
        recall_src = _fixtures_dir() / "recall_at_k_gold.json"
        (tmp_path / "recall_at_k_gold.json").write_bytes(recall_src.read_bytes())

        # Write a perturbed fixture (flip expected_routed for all cases) into tmp_path
        cases = _load_eval_cases()
        perturbed = []
        for c in cases:
            p = dict(c)
            p["expected_routed"] = not c["expected_routed"]
            p["expected_queue"] = None
            p["expected_reason"] = None
            perturbed.append(p)

        perturbed_path = tmp_path / "eval_cases.synthetic.json"
        perturbed_path.write_text(json.dumps(perturbed), encoding="utf-8")

        # Monkey-patch the fixtures dir for this test only
        import app.eval.harness as harness_mod
        orig_dir = harness_mod._fixtures_dir

        def _patched_dir():
            return tmp_path

        harness_mod._fixtures_dir = _patched_dir
        try:
            perturbed_result = run_eval()
        finally:
            harness_mod._fixtures_dir = orig_dir

        # Routing accuracy must differ (at least some correct → now incorrect)
        assert perturbed_result["routing_accuracy"] != baseline["routing_accuracy"], (
            "Perturbing fixture labels must change routing_accuracy — "
            "proves the metric is computed, not fabricated"
        )


# ---------------------------------------------------------------------------
# EVAL2 / LEAK4 — No contamination (RULE_NO_EVAL_CONTAMINATION)
# ---------------------------------------------------------------------------

class TestEVAL2:
    """EVAL2 / LEAK4: the harness proves the eval questionnaire is held out.

    A deliberate contamination attempt is detected and fails the check.
    """

    def test_no_contamination_passes_for_valid_eval_cases(self):
        """EVAL2: check_no_contamination passes for the shipped eval cases."""
        from app.eval.harness import check_no_contamination, _load_eval_cases
        from app.kb import load_kb

        eval_cases = _load_eval_cases()
        kb_chunks = load_kb()

        # Should not raise
        check_no_contamination(eval_cases, kb_chunks)

    def test_contamination_attempt_is_detected(self):
        """EVAL2 / LEAK4: injecting a KB chunk question as an eval-case question
        is detected and rejected (RULE_NO_EVAL_CONTAMINATION fires)."""
        from app.eval.harness import check_no_contamination
        from app.kb import load_kb

        kb_chunks = load_kb()
        # Find a real KB chunk question to use as a contaminated eval case
        contaminated_question = next(
            c.question for c in kb_chunks if c.question and c.approved
        )

        # Build a fake eval case that matches a KB question verbatim
        contaminated_cases = [
            {
                "item_id": "eval-contaminated",
                "question": contaminated_question,
                "expected_routed": False,
                "expected_grounded": True,
            }
        ]

        with pytest.raises(ValueError, match="RULE_NO_EVAL_CONTAMINATION"):
            check_no_contamination(contaminated_cases, kb_chunks)

    def test_eval_harness_never_mutates_production_kb(self):
        """EVAL2 / LEAK4: run_eval() does not modify any data/kb/* files."""
        import hashlib
        from app.eval.harness import run_eval

        kb_dir = REPO_ROOT / "data" / "kb"
        kb_files = list(kb_dir.rglob("*.json"))

        def _hash_files(files):
            h = {}
            for f in files:
                h[str(f)] = hashlib.md5(f.read_bytes()).hexdigest()
            return h

        before = _hash_files(kb_files)
        run_eval()  # run the full eval
        after = _hash_files(kb_files)

        for fpath, before_hash in before.items():
            assert after[fpath] == before_hash, (
                f"RULE_NO_EVAL_CONTAMINATION: run_eval() mutated KB file {fpath}"
            )

    def test_run_eval_does_not_write_to_data_dir(self, tmp_path):
        """EVAL2: run_eval() writes no files into data/ — production KB is read-only."""
        from app.eval.harness import run_eval

        data_dir = REPO_ROOT / "data"
        before_files = set(data_dir.rglob("*"))
        run_eval()
        after_files = set(data_dir.rglob("*"))

        new_files = after_files - before_files
        assert not new_files, (
            f"run_eval() wrote new files into data/: {new_files} "
            f"(RULE_NO_EVAL_CONTAMINATION: production KB must not be mutated)"
        )


# ---------------------------------------------------------------------------
# EVAL3 — Calibration is real (computed, not asserted as literals)
# ---------------------------------------------------------------------------

class TestEVAL3:
    """EVAL3: confidence calibration is computed over the held-out set, not asserted."""

    def test_calibration_computed_not_hardcoded(self):
        """EVAL3: calibration counts come from actually scoring the eval cases."""
        from app.eval.harness import run_eval

        result = run_eval()
        cal = result["calibration"]

        # The total must match n_eval_cases — proves it was computed per-case
        n = result["n_eval_cases"]
        total = sum(v["grounded"] + v["ungrounded"] for v in cal.values())
        assert total == n

    def test_calibration_reflects_confidence_band_distribution(self):
        """EVAL3: calibration bands map directly from confidence_band() — no manual assignment."""
        from app.eval.harness import run_eval, _load_eval_cases
        from app.kb import load_kb, load_policy_tags
        from app.retrieval import Retriever
        from app.confidence import score_confidence, confidence_band
        from app.draft import GroundingResult
        from app.schema import DraftAnswer, Citation, QuestionnaireItem
        from app.eval.harness import _simulate_grounding

        # Re-derive the calibration independently and check it matches run_eval()
        cases = _load_eval_cases()
        kb = load_kb()
        r = Retriever(kb)

        expected_auto_grounded = 0
        expected_auto_ungrounded = 0
        expected_review_grounded = 0
        expected_review_ungrounded = 0

        for case in cases:
            chunks = r.retrieve(
                question=case["question"],
                topic_tags=case.get("topic_tags") or None,
            )
            grounding = _simulate_grounding(chunks)
            conf = score_confidence(chunks, grounding, case["question"])
            band = confidence_band(conf.score)
            if band == "auto":
                if grounding.grounded:
                    expected_auto_grounded += 1
                else:
                    expected_auto_ungrounded += 1
            else:
                if grounding.grounded:
                    expected_review_grounded += 1
                else:
                    expected_review_ungrounded += 1

        result = run_eval()
        cal = result["calibration"]
        assert cal["auto"]["grounded"] == expected_auto_grounded
        assert cal["auto"]["ungrounded"] == expected_auto_ungrounded
        assert cal["review"]["grounded"] == expected_review_grounded
        assert cal["review"]["ungrounded"] == expected_review_ungrounded

    def test_calibration_has_non_trivial_content(self):
        """EVAL3: calibration is non-trivial — at least one band has entries."""
        from app.eval.harness import run_eval

        result = run_eval()
        cal = result["calibration"]

        total = sum(v["grounded"] + v["ungrounded"] for v in cal.values())
        assert total > 0, "Calibration is empty — no eval cases were scored"


# ---------------------------------------------------------------------------
# Confidence refactor — score VALUE unchanged (CONF1–CONF3 regression)
# ---------------------------------------------------------------------------

class TestConfidenceRefactor:
    """Regression tests confirming the Stage 7 _compute_score refactor
    does not alter the numeric score value (CONF1–CONF3 contracts intact)."""

    def test_compute_score_still_returns_float(self):
        """Stage 7 refactor: _compute_score() still returns float (backward compat)."""
        from app.confidence import _compute_score
        from app.draft import GroundingResult
        from app.schema import DraftAnswer, Citation

        chunks = [_make_chunk("c1", "AES-256 encryption at rest.", bm25_score=2.0)]
        grounding = GroundingResult(
            grounded=True,
            answer=DraftAnswer(text="AES-256 encryption.", citations=[Citation(chunk_id="c1")]),
            reason_code=None,
        )
        result = _compute_score(chunks, grounding, "How is data encrypted?")
        assert isinstance(result, float), (
            f"_compute_score() must return float; got {type(result)}"
        )
        assert 0.0 <= result <= 1.0

    def test_compute_score_value_matches_score_confidence_score(self):
        """Stage 7: _compute_score() float equals score_confidence().score — no value change."""
        from app.confidence import _compute_score, score_confidence
        from app.draft import GroundingResult
        from app.schema import DraftAnswer, Citation

        chunks = [
            _make_chunk("c1", "AES-256 encryption at rest.", bm25_score=2.5),
            _make_chunk("c2", "Backups encrypted with same key.", bm25_score=1.0),
        ]
        grounding = GroundingResult(
            grounded=True,
            answer=DraftAnswer(text="AES-256.", citations=[Citation(chunk_id="c1")]),
            reason_code=None,
        )
        question = "How is data encrypted at rest?"

        pure_float = _compute_score(chunks, grounding, question)
        result = score_confidence(chunks, grounding, question)

        assert pure_float == result.score, (
            f"_compute_score (float) {pure_float} != score_confidence.score {result.score}; "
            "Stage 7 refactor must not change the score value"
        )

    def test_rationale_matches_scored_components(self):
        """Stage 7 refactor: rationale text reflects the EXACT components used in the score."""
        from app.confidence import score_confidence
        from app.draft import GroundingResult
        from app.schema import DraftAnswer, Citation

        chunks = [_make_chunk("c1", "We use AES-256 encryption.", bm25_score=3.0)]
        grounding = GroundingResult(
            grounded=True,
            answer=DraftAnswer(text="AES-256 encryption.", citations=[Citation(chunk_id="c1")]),
            reason_code=None,
        )
        result = score_confidence(chunks, grounding, "How is data encrypted?")

        # The rationale must contain the score formatted to 3 decimal places
        expected_score_str = f"{result.score:.3f}"
        assert expected_score_str in result.rationale, (
            f"Rationale does not contain the formatted score {expected_score_str!r}; "
            f"rationale: {result.rationale!r}"
        )


# ---------------------------------------------------------------------------
# New config constants (Stage 7 additions)
# ---------------------------------------------------------------------------

class TestStage7ConfigConstants:
    """Verify the 3 new §9 constants added in Stage 7 (Asaf-authorized)."""

    def test_sensitivity_review_queue_defined(self):
        """SENSITIVITY_REVIEW_QUEUE = 'compliance' is defined in config."""
        from app.config import SENSITIVITY_REVIEW_QUEUE
        assert SENSITIVITY_REVIEW_QUEUE == "compliance"

    def test_routed_sensitive_defined(self):
        """ROUTED_SENSITIVE = 'ROUTED_SENSITIVE' is defined in config."""
        from app.config import ROUTED_SENSITIVE
        assert ROUTED_SENSITIVE == "ROUTED_SENSITIVE"

    def test_compliance_in_reviewer_queues(self):
        """'compliance' appears in REVIEWER_QUEUES (Stage 7 append)."""
        from app.config import REVIEWER_QUEUES
        assert "compliance" in REVIEWER_QUEUES

    def test_sensitivity_review_queue_in_reviewer_queues(self):
        """SENSITIVITY_REVIEW_QUEUE is ∈ REVIEWER_QUEUES (DATA1 cross-check)."""
        from app.config import SENSITIVITY_REVIEW_QUEUE, REVIEWER_QUEUES
        assert SENSITIVITY_REVIEW_QUEUE in REVIEWER_QUEUES

    def test_routed_sensitive_in_routing_py(self):
        """ROUTED_SENSITIVE is referenced in app/routing.py (the chokepoint)."""
        from app.config import ROUTED_SENSITIVE
        content = (REPO_ROOT / "app" / "routing.py").read_text(encoding="utf-8")
        assert ROUTED_SENSITIVE in content

    def test_sensitivity_review_queue_in_routing_py(self):
        """SENSITIVITY_REVIEW_QUEUE is used in app/routing.py."""
        content = (REPO_ROOT / "app" / "routing.py").read_text(encoding="utf-8")
        assert "SENSITIVITY_REVIEW_QUEUE" in content
