"""
tests/test_stage2.py — Offline deterministic suite for Stage 2.

Covers: RET1, RET2, RET3, and progressive ENV4 (app.retrieval, app.eval.rubric,
app.eval.fixtures added to the import-safety set).

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: seeded where needed; rank_bm25 is deterministic.

QA check mapping:
  RET1 — retrieve() returns ≤ RETRIEVAL_TOP_K approved chunks; filters work; no network
  RET2 — compute_recall_at_k over gold_fixtures meets RECALL_AT_K_TARGET (computed, not hardcoded)
  RET3 — determinism: two sequential retrieve() calls return identical ranked chunk_id lists
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"


# ---------------------------------------------------------------------------
# Progressive ENV4 — import-safety for Stage 2 modules
# ---------------------------------------------------------------------------

class TestENV4Stage2:
    """ENV4 (progressive): Stage 2 modules import without side effects.

    Adds app.retrieval, app.eval.rubric, app.eval.fixtures to the tested set.
    Stage 1 modules (app.config, app.schema, app.kb) are already covered in test_stage1.py.
    """

    MODULES_TO_TEST = [
        "app.config",
        "app.schema",
        "app.kb",
        "app.retrieval",
        "app.eval.rubric",
        "app.eval.fixtures",
    ]

    def test_stage2_modules_import_cleanly(self):
        """Stage 2 app.* modules import without raising in a subprocess with no .env."""
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
            f"Import of Stage 2 app modules failed:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_retrieval_no_side_effects_at_import(self):
        """app.retrieval imports with no KB read, no network, no .env."""
        # In-process import — module should define no module-level work
        import app.retrieval  # noqa: F401
        # If we get here without error, import is safe

    def test_eval_modules_no_side_effects_at_import(self):
        """app.eval.fixtures and app.eval.rubric import cleanly in-process."""
        import app.eval.fixtures  # noqa: F401
        import app.eval.rubric    # noqa: F401


# ---------------------------------------------------------------------------
# RET1 — retrieve() returns ≤ RETRIEVAL_TOP_K approved chunks; filters work
# ---------------------------------------------------------------------------

class TestRET1:
    """RET1: retrieve() returns ≤ RETRIEVAL_TOP_K approved chunks;
    topic/sensitivity filters applied; non-approved never returned; no network.
    """

    def setup_method(self):
        from app.retrieval import retrieve
        from app.config import RETRIEVAL_TOP_K, BM25_K1, BM25_B
        self.retrieve = retrieve
        self.top_k = RETRIEVAL_TOP_K
        self.bm25_k1 = BM25_K1
        self.bm25_b = BM25_B

    def test_returns_at_most_top_k_chunks(self):
        """retrieve() returns ≤ RETRIEVAL_TOP_K chunks."""
        results = self.retrieve("data encryption security compliance", top_k=self.top_k)
        assert len(results) <= self.top_k, (
            f"retrieve() returned {len(results)} chunks; expected ≤ {self.top_k}"
        )

    def test_returns_only_approved_chunks(self):
        """All returned chunks must have approved == True (non-approved never retrievable)."""
        results = self.retrieve("vulnerability disclosure penetration testing", top_k=self.top_k)
        for chunk in results:
            assert chunk.approved, (
                f"Non-approved chunk '{chunk.chunk_id}' returned by retrieve() — KB1 violated"
            )

    def test_non_approved_chunk_never_returned(self):
        """The specific non-approved chunk kb-014 must never appear in results."""
        from app.kb import load_kb
        all_chunks = load_kb()
        non_approved_ids = {c.chunk_id for c in all_chunks if not c.approved}
        assert non_approved_ids, "Test requires at least one non-approved chunk in KB"

        # Use a query that is very close to kb-014's question text
        results = self.retrieve(
            "vulnerability disclosure policy penetration testing",
            top_k=self.top_k,
        )
        returned_ids = {c.chunk_id for c in results}
        overlap = returned_ids.intersection(non_approved_ids)
        assert not overlap, (
            f"Non-approved chunks {overlap} appeared in retrieve() results"
        )

    def test_topic_filter_restricts_corpus(self):
        """Topic filter: only chunks sharing ≥1 topic tag are returned."""
        results = self.retrieve("data security", topic_tags=["encryption"], top_k=self.top_k)
        for chunk in results:
            assert "encryption" in chunk.topic_tags, (
                f"Chunk '{chunk.chunk_id}' lacks topic tag 'encryption' but was returned "
                f"when topic_tags=['encryption'] filter was applied. Tags: {chunk.topic_tags}"
            )

    def test_topic_filter_empty_list_is_no_filter(self):
        """Empty topic_tags list = no restriction (same as None)."""
        results_no_filter = self.retrieve("encryption security", topic_tags=None, top_k=self.top_k)
        results_empty = self.retrieve("encryption security", topic_tags=[], top_k=self.top_k)
        # BM25 scores should be identical since corpus is not filtered either way
        ids_no_filter = [c.chunk_id for c in results_no_filter]
        ids_empty = [c.chunk_id for c in results_empty]
        assert ids_no_filter == ids_empty, (
            "Empty topic_tags=[] produced different results than topic_tags=None"
        )

    def test_sensitivity_filter_restricts_corpus(self):
        """Sensitivity filter: only chunks with sensitivity in allowed_sensitivities returned."""
        results = self.retrieve(
            "data storage location compliance",
            allowed_sensitivities=["public"],
            top_k=self.top_k,
        )
        for chunk in results:
            assert chunk.sensitivity == "public", (
                f"Chunk '{chunk.chunk_id}' has sensitivity '{chunk.sensitivity}' but only "
                f"'public' was requested via allowed_sensitivities"
            )

    def test_sensitivity_filter_none_allows_all(self):
        """allowed_sensitivities=None (default) allows all sensitivity levels."""
        # With no filter, internal/restricted chunks may appear
        results = self.retrieve(
            "data storage location customer region",
            allowed_sensitivities=None,
            top_k=self.top_k,
        )
        sensitivities = {c.sensitivity for c in results}
        # Internal chunk kb-009 is about data storage, should appear without filter
        # We can't assert exactly, but we assert the call doesn't error and returns chunks
        assert len(results) > 0, "retrieve() with no sensitivity filter returned empty results"

    def test_combined_topic_and_sensitivity_filter(self):
        """Both filters can be applied simultaneously."""
        results = self.retrieve(
            "access control security compliance",
            topic_tags=["access-control"],
            allowed_sensitivities=["public"],
            top_k=self.top_k,
        )
        for chunk in results:
            assert "access-control" in chunk.topic_tags, (
                f"Chunk '{chunk.chunk_id}' lacks 'access-control' topic tag"
            )
            assert chunk.sensitivity == "public", (
                f"Chunk '{chunk.chunk_id}' has sensitivity '{chunk.sensitivity}' != 'public'"
            )

    def test_empty_corpus_after_filter_returns_empty_list(self):
        """If all chunks are filtered out, retrieve() returns [] (not an error)."""
        results = self.retrieve(
            "encryption security",
            topic_tags=["nonexistent-tag-xyz-12345"],
            top_k=self.top_k,
        )
        assert results == [], (
            f"Expected [] when corpus is empty after topic filter; got {results}"
        )

    def test_bm25_score_is_set_on_returned_chunks(self):
        """Returned chunks must have bm25_score set (not the default 0.0 from KB load)."""
        results = self.retrieve("encryption data security", top_k=self.top_k)
        assert results, "Expected non-empty results"
        # The top result should have a positive BM25 score
        assert results[0].bm25_score > 0.0, (
            f"Top chunk '{results[0].chunk_id}' has bm25_score={results[0].bm25_score}; "
            f"expected a positive score"
        )

    def test_results_sorted_descending_by_score(self):
        """Results must be sorted by bm25_score descending."""
        results = self.retrieve("encryption security compliance data", top_k=self.top_k)
        scores = [c.bm25_score for c in results]
        assert scores == sorted(scores, reverse=True), (
            f"Results are not sorted by bm25_score descending: {scores}"
        )

    def test_uses_bm25_k1_and_b_from_config(self):
        """Sanity: BM25_K1 and BM25_B constants are in range (they are passed to BM25Okapi)."""
        # Verifying the constants are sensible; the actual usage is proven by the scores
        assert 0.0 < self.bm25_k1 <= 3.0, f"BM25_K1={self.bm25_k1} out of sensible range"
        assert 0.0 <= self.bm25_b <= 1.0, f"BM25_B={self.bm25_b} out of sensible range"

    def test_no_network_import(self):
        """app.retrieval imports without network (rank_bm25 is a local lib)."""
        # The import itself proves this; if it required network it would fail offline.
        # We additionally verify that rank_bm25 is in requirements.txt.
        req_path = REPO_ROOT / "requirements.txt"
        content = req_path.read_text(encoding="utf-8")
        assert "rank-bm25==" in content or "rank_bm25==" in content, (
            "rank_bm25 / rank-bm25 is not pinned in requirements.txt (ENV2)"
        )


# ---------------------------------------------------------------------------
# RET2 — Recall@K computed over gold_fixtures; meets RECALL_AT_K_TARGET
# ---------------------------------------------------------------------------

class TestRET2:
    """RET2: compute_recall_at_k over fixtures/eval/ gold returns a computed float
    meeting RECALL_AT_K_TARGET. The metric is computed, never hardcoded.
    """

    def setup_method(self):
        from app.eval.fixtures import load_eval_fixtures
        from app.eval.rubric import compute_recall_at_k
        from app.config import RETRIEVAL_TOP_K, RECALL_AT_K_TARGET
        self.load_fixtures = load_eval_fixtures
        self.compute_recall = compute_recall_at_k
        self.top_k = RETRIEVAL_TOP_K
        self.target = RECALL_AT_K_TARGET

    def test_recall_at_k_meets_target(self):
        """Recall@K computed over gold_fixtures meets RECALL_AT_K_TARGET.

        RULE_NO_FABRICATED_METRIC: the score is computed by compute_recall_at_k(),
        not asserted as a literal.
        """
        fixtures = self.load_fixtures()
        assert len(fixtures) >= 8, (
            f"Expected ≥8 labeled fixtures for meaningful Recall@K; found {len(fixtures)}"
        )
        recall = self.compute_recall(fixtures, k=self.top_k)
        assert isinstance(recall, float), f"compute_recall_at_k must return float; got {type(recall)}"
        assert 0.0 <= recall <= 1.0, f"Recall@K must be in [0, 1]; got {recall}"
        assert recall >= self.target, (
            f"Recall@{self.top_k} = {recall:.4f} is below RECALL_AT_K_TARGET={self.target}. "
            f"This is the REAL measured value — do not tune the metric or fixtures to pass."
        )

    def test_recall_is_computed_not_hardcoded(self):
        """Perturbing a fixture changes the Recall@K result (proving it is computed)."""
        fixtures = self.load_fixtures()

        # Compute baseline recall
        baseline = self.compute_recall(fixtures, k=self.top_k)

        # Perturb: replace relevant_chunk_ids with a non-existent ID so it never hits
        perturbed_fixtures = []
        for f in fixtures:
            perturbed_fixtures.append({
                "query": f["query"],
                "relevant_chunk_ids": ["chunk-id-that-does-not-exist-xyz-99999"],
                "topic_tags": f.get("topic_tags", []),
            })

        perturbed_recall = self.compute_recall(perturbed_fixtures, k=self.top_k)
        assert perturbed_recall == 0.0, (
            f"Expected Recall@K=0.0 when all relevant_chunk_ids are non-existent; "
            f"got {perturbed_recall} — metric is not correctly computed"
        )
        assert baseline != perturbed_recall, (
            "Recall@K did not change when fixtures were perturbed — metric may be hardcoded"
        )

    def test_fixtures_load_without_error(self):
        """fixtures/eval/ loads ≥8 records without error."""
        fixtures = self.load_fixtures()
        assert len(fixtures) >= 8, f"Expected ≥8 fixtures; got {len(fixtures)}"
        for i, f in enumerate(fixtures):
            assert "query" in f, f"Fixture {i} missing 'query'"
            assert "relevant_chunk_ids" in f, f"Fixture {i} missing 'relevant_chunk_ids'"
            assert isinstance(f["relevant_chunk_ids"], list), (
                f"Fixture {i} 'relevant_chunk_ids' is not a list"
            )

    def test_relevant_chunk_ids_exist_in_kb(self):
        """Every relevant_chunk_id in the gold fixtures exists in the KB (sanity check)."""
        from app.kb import load_kb
        fixtures = self.load_fixtures()
        all_kb_ids = {c.chunk_id for c in load_kb()}
        for i, f in enumerate(fixtures):
            for cid in f["relevant_chunk_ids"]:
                assert cid in all_kb_ids, (
                    f"Fixture {i}: relevant_chunk_id '{cid}' does not exist in the KB. "
                    f"Fixtures must label chunks that are actually in the KB (Recall@K, "
                    f"not answer-eval contamination)."
                )

    def test_empty_fixtures_returns_zero(self):
        """compute_recall_at_k([]) returns 0.0 (edge case guard)."""
        recall = self.compute_recall([], k=self.top_k)
        assert recall == 0.0, f"Expected 0.0 for empty fixtures; got {recall}"

    def test_recall_at_k_is_float_in_range(self):
        """The computed Recall@K value is a float in [0.0, 1.0]."""
        fixtures = self.load_fixtures()
        recall = self.compute_recall(fixtures, k=self.top_k)
        assert isinstance(recall, float)
        assert 0.0 <= recall <= 1.0


# ---------------------------------------------------------------------------
# RET3 — Determinism: identical ranked chunk_id list across runs
# ---------------------------------------------------------------------------

class TestRET3:
    """RET3: two sequential retrieve() calls on the same query + KB return
    identical ranked chunk_id lists (no set/dict ordering nondeterminism).
    """

    def setup_method(self):
        from app.retrieval import retrieve
        from app.config import RETRIEVAL_TOP_K
        self.retrieve = retrieve
        self.top_k = RETRIEVAL_TOP_K

    def test_identical_results_across_sequential_calls(self):
        """Same query → same ranked chunk_id list on two consecutive calls."""
        query = "encryption data security compliance certification"
        results1 = self.retrieve(query, top_k=self.top_k)
        results2 = self.retrieve(query, top_k=self.top_k)
        ids1 = [c.chunk_id for c in results1]
        ids2 = [c.chunk_id for c in results2]
        assert ids1 == ids2, (
            f"RET3: retrieve() produced different results on sequential calls.\n"
            f"Run 1: {ids1}\nRun 2: {ids2}"
        )

    def test_determinism_with_topic_filter(self):
        """Determinism holds when topic_tags filter is applied."""
        query = "security incident response breach notification"
        results1 = self.retrieve(query, topic_tags=["security"], top_k=self.top_k)
        results2 = self.retrieve(query, topic_tags=["security"], top_k=self.top_k)
        ids1 = [c.chunk_id for c in results1]
        ids2 = [c.chunk_id for c in results2]
        assert ids1 == ids2, (
            f"RET3: retrieve() with topic filter produced different results.\n"
            f"Run 1: {ids1}\nRun 2: {ids2}"
        )

    def test_determinism_with_sensitivity_filter(self):
        """Determinism holds when allowed_sensitivities filter is applied."""
        query = "data storage location geographic region"
        results1 = self.retrieve(query, allowed_sensitivities=["public", "internal"], top_k=self.top_k)
        results2 = self.retrieve(query, allowed_sensitivities=["public", "internal"], top_k=self.top_k)
        ids1 = [c.chunk_id for c in results1]
        ids2 = [c.chunk_id for c in results2]
        assert ids1 == ids2, (
            f"RET3: retrieve() with sensitivity filter produced different results.\n"
            f"Run 1: {ids1}\nRun 2: {ids2}"
        )

    def test_tiebreak_by_chunk_id(self):
        """Equal-score chunks must be broken by chunk_id ascending (deterministic)."""
        # Use a very short/generic query that will produce many tied 0.0-score chunks
        # The tiebreak ensures a reproducible order even among zero-score results.
        query = "zzzzunlikelytermxxx"
        results1 = self.retrieve(query, top_k=self.top_k)
        results2 = self.retrieve(query, top_k=self.top_k)
        ids1 = [c.chunk_id for c in results1]
        ids2 = [c.chunk_id for c in results2]
        assert ids1 == ids2, (
            f"RET3: tiebreak failed — zero-score results differ between calls.\n"
            f"Run 1: {ids1}\nRun 2: {ids2}"
        )
        # If there are tied scores, verify chunk_ids are ascending within each score group
        scores = [c.bm25_score for c in results1]
        ids = [c.chunk_id for c in results1]
        prev_score = None
        tie_group: list[str] = []
        for s, cid in zip(scores, ids):
            if s != prev_score:
                if tie_group:
                    assert tie_group == sorted(tie_group), (
                        f"Tied-score group not sorted by chunk_id ascending: {tie_group}"
                    )
                tie_group = [cid]
                prev_score = s
            else:
                tie_group.append(cid)
        if tie_group:
            assert tie_group == sorted(tie_group), (
                f"Final tied-score group not sorted by chunk_id ascending: {tie_group}"
            )

    def test_scores_same_across_calls(self):
        """BM25 scores must be identical (not just the order) across sequential calls."""
        query = "access control multi-factor authentication MFA"
        results1 = self.retrieve(query, top_k=self.top_k)
        results2 = self.retrieve(query, top_k=self.top_k)
        scores1 = [c.bm25_score for c in results1]
        scores2 = [c.bm25_score for c in results2]
        assert scores1 == scores2, (
            f"RET3: BM25 scores differ between calls.\n"
            f"Run 1: {scores1}\nRun 2: {scores2}"
        )


# ---------------------------------------------------------------------------
# Additional: deferred kb.py fixes verification
# ---------------------------------------------------------------------------

class TestKBFixes:
    """Verify the two deferred Stage-1 kb.py findings are fixed.

    1. The dead `and required_field != 'approved'` sub-condition is removed.
    2. chunk_id uniqueness is enforced across approved_answers + docs.
    """

    def test_duplicate_chunk_id_raises_value_error(self, tmp_path, monkeypatch):
        """A KB with duplicate chunk_ids (across approved_answers) must raise ValueError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"chunk_id": "dup-001", "answer": "First answer.", "sensitivity": "public", "approved": True},
            {"chunk_id": "dup-001", "answer": "Duplicate chunk id.", "sensitivity": "public", "approved": True},
        ]))
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)

        with pytest.raises(ValueError, match="Duplicate chunk_id"):
            kb_module.load_kb()

    def test_duplicate_chunk_id_across_docs_raises_value_error(self, tmp_path, monkeypatch):
        """A duplicate chunk_id across approved_answers and docs must raise ValueError."""
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir(parents=True)
        docs_dir = kb_dir / "docs"
        docs_dir.mkdir()

        # approved_answers has chunk "shared-001"
        (kb_dir / "approved_answers.synthetic.json").write_text(json.dumps([
            {"chunk_id": "shared-001", "answer": "From approved_answers.", "sensitivity": "public", "approved": True},
        ]))
        # docs also has "shared-001"
        (docs_dir / "extra.synthetic.json").write_text(json.dumps([
            {"chunk_id": "shared-001", "answer": "Collision from docs.", "sensitivity": "public", "approved": True},
        ]))

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)

        with pytest.raises(ValueError, match="Duplicate chunk_id"):
            kb_module.load_kb()

    def test_empty_chunk_id_raises_value_error(self, tmp_path, monkeypatch):
        """A record with an empty chunk_id must raise ValueError (dead sub-condition fix)."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"chunk_id": "", "answer": "Answer text here.", "sensitivity": "public", "approved": True},
        ]))
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)

        # After removing the dead `!= "approved"` sub-condition, an empty chunk_id
        # must now raise ValueError (previously the check was skipped due to the bug)
        with pytest.raises(ValueError, match="empty required field"):
            kb_module.load_kb()

    def test_empty_answer_raises_value_error(self, tmp_path, monkeypatch):
        """A record with an empty answer must raise ValueError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"chunk_id": "c1", "answer": "", "sensitivity": "public", "approved": True},
        ]))
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)

        with pytest.raises(ValueError, match="empty required field"):
            kb_module.load_kb()

    def test_real_kb_has_unique_chunk_ids(self):
        """The real synthetic KB must have globally unique chunk_ids (integration check)."""
        from app.kb import load_kb
        chunks = load_kb()
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), (
            f"Duplicate chunk_ids found in real KB: "
            f"{[cid for cid in set(ids) if ids.count(cid) > 1]}"
        )
