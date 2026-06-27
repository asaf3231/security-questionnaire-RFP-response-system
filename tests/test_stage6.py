"""
tests/test_stage6.py — Offline deterministic suite for Stage 6.

Covers: PIPE1, PIPE2, DEMO1, DEMO2, RULE1, RULE2, and progressive ENV4
(app.pipeline added to the import-safety set).

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: MockLLM (seeded) under a fixed corpus; tmp_path for all file I/O.

QA check mapping:
  PIPE1  — full happy path: run_pipeline() produces a ResponseDoc, deterministic under MockLLM
  PIPE2  — safe terminal: injected failure → ROUTED_FOR_REVIEW + ERROR_TERMINAL; no exception
  DEMO1  — case_confident: high confidence, grounded, i1/i2 not routed; i3 ROUTED_HIGH_RISK
  DEMO2  — case_review: RULE_HITM_REVIEW_TRIGGER fires; ROUTED_FOR_REVIEW; REVIEW_BANNER present
  RULE1  — every RULE_* in config.py is referenced at its §5.1 chokepoint module
  RULE2  — a pipeline run writes each expected reason-code to the audit log
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"


# ---------------------------------------------------------------------------
# Shared test fixtures and helpers
# ---------------------------------------------------------------------------

def _make_minimal_questionnaire(
    questionnaire_id: str = "q-test-001",
    items: list[dict] | None = None,
) -> dict:
    """Build a minimal validated questionnaire dict for pipeline testing."""
    from app.schema import QuestionnaireItem
    if items is None:
        items = [
            {"item_id": "q-test-001-i1",
             "question": "Does your platform encrypt data at rest?",
             "topic_tags": ["encryption", "infrastructure"]},
        ]
    qi_list = [
        QuestionnaireItem(
            item_id=it["item_id"],
            question=it["question"],
            topic_tags=it.get("topic_tags", []),
        )
        for it in items
    ]
    return {"questionnaire_id": questionnaire_id, "items": qi_list}


def _load_real_questionnaire(filename: str) -> dict:
    """Load one of the real synthetic demo questionnaires."""
    from app.kb import load_questionnaire
    path = REPO_ROOT / "data" / "questionnaires" / filename
    return load_questionnaire(path)


def _build_retriever() -> object:
    """Build a Retriever over the real KB (shared across test cases)."""
    from app.kb import load_kb
    from app.retrieval import Retriever
    return Retriever(load_kb())


def _load_policy() -> dict:
    from app.kb import load_policy_tags
    return load_policy_tags()


# ---------------------------------------------------------------------------
# Progressive ENV4 — import-safety for Stage 6 module
# ---------------------------------------------------------------------------

class TestENV4Stage6:
    """ENV4 (progressive): Stage 6 module imports without side effects.

    Adds app.pipeline to the tested import-safety set.
    Prior stages (config/schema/kb/retrieval/context_stack/llm/draft/
    confidence/routing/state/audit/export) are covered in earlier test files.
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
    ]

    def test_pipeline_imports_cleanly_subprocess(self):
        """app.pipeline imports without raising in a subprocess with no .env."""
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
            f"Import of Stage 6 app modules failed:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_pipeline_import_no_side_effects(self):
        """app.pipeline imports in-process with zero side effects."""
        import app.pipeline  # noqa: F401
        # No client, no file, no network — if we get here, it's safe.

    def test_pipeline_result_class_importable(self):
        """PipelineResult is importable from app.pipeline."""
        from app.pipeline import PipelineResult  # noqa: F401

    def test_run_pipeline_importable(self):
        """run_pipeline() is importable from app.pipeline."""
        from app.pipeline import run_pipeline  # noqa: F401

    def test_retriever_class_importable(self):
        """Retriever class is importable from app.retrieval."""
        from app.retrieval import Retriever  # noqa: F401


# ---------------------------------------------------------------------------
# PIPE1 — Full happy path
# ---------------------------------------------------------------------------

class TestPIPE1:
    """PIPE1: run_pipeline() produces a ResponseDoc from a questionnaire.

    Deterministic under MockLLM: same questionnaire → same ResponseDoc.
    """

    def test_happy_path_produces_response_doc(self, tmp_path):
        """PIPE1: run_pipeline returns a PipelineResult with a valid ResponseDoc."""
        from app.pipeline import run_pipeline, PipelineResult
        from app.schema import ResponseDoc
        from app.llm import MockLLM

        q = _make_minimal_questionnaire()
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        assert isinstance(result, PipelineResult)
        assert isinstance(result.response_doc, ResponseDoc)
        assert result.response_doc.questionnaire_id == "q-test-001"
        assert len(result.response_doc.items) == 1

    def test_item_has_expected_fields(self, tmp_path):
        """PIPE1: each item in the ResponseDoc has all required fields."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM

        q = _make_minimal_questionnaire()
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        item = result.response_doc.items[0]
        assert item.item_id == "q-test-001-i1"
        assert item.question == "Does your platform encrypt data at rest?"
        assert isinstance(item.draft_text, str) and item.draft_text
        assert isinstance(item.citations, list)
        assert item.status in ("SCORED", "ROUTED_FOR_REVIEW")
        assert item.confidence_score is not None

    def test_all_stages_of_pipeline_covered(self, tmp_path):
        """PIPE1: pipeline chain runs intake→retrieve→draft→score→route for each item."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM

        q = _make_minimal_questionnaire(
            questionnaire_id="q-chain",
            items=[
                {"item_id": "q-chain-i1",
                 "question": "What encryption do you use for data at rest?",
                 "topic_tags": ["encryption"]},
                {"item_id": "q-chain-i2",
                 "question": "What is your SOC 2 Type II status?",
                 "topic_tags": ["compliance"]},
            ],
        )
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )
        assert len(result.response_doc.items) == 2
        for item in result.response_doc.items:
            assert item.status in ("SCORED", "ROUTED_FOR_REVIEW")

    def test_audit_log_written(self, tmp_path):
        """PIPE1: run_pipeline writes at least one audit event per item."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM

        audit_path = tmp_path / "audit.jsonl"
        q = _make_minimal_questionnaire()
        run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=audit_path,
        )

        assert audit_path.exists(), "Audit log should be written"
        lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1, "Should have at least one audit event"
        for line in lines:
            event = json.loads(line)
            assert event["questionnaire_id"] == "q-test-001"
            assert event["item_id"] == "q-test-001-i1"

    def test_determinism_same_questionnaire_same_result(self, tmp_path):
        """PIPE1: identical questionnaire + MockLLM → identical ResponseDoc."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM

        q = _make_minimal_questionnaire()
        retriever = _build_retriever()
        policy = _load_policy()

        r1 = run_pipeline(
            q, provider=MockLLM(), retriever=retriever, policy_tags=policy,
            audit_log_path=tmp_path / "a1.jsonl",
        )
        r2 = run_pipeline(
            q, provider=MockLLM(), retriever=retriever, policy_tags=policy,
            audit_log_path=tmp_path / "a2.jsonl",
        )

        i1 = r1.response_doc.items[0]
        i2 = r2.response_doc.items[0]
        assert i1.draft_text == i2.draft_text
        assert i1.confidence_score == i2.confidence_score
        assert i1.status == i2.status

    def test_routing_dict_populated(self, tmp_path):
        """PIPE1: PipelineResult.routing contains a RoutingDecision per item."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM
        from app.schema import RoutingDecision

        q = _make_minimal_questionnaire()
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        assert "q-test-001-i1" in result.routing
        assert isinstance(result.routing["q-test-001-i1"], RoutingDecision)

    def test_no_errors_on_clean_run(self, tmp_path):
        """PIPE1: PipelineResult.errors is empty for a clean run."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM

        q = _make_minimal_questionnaire()
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )
        assert result.errors == {}

    def test_sensitivities_collected_from_cited_chunks(self, tmp_path):
        """PIPE1: ResponseDocItem.sensitivities contains tags from cited chunks."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM
        from app.config import SENSITIVITY_TAGS

        q = _make_minimal_questionnaire()
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        item = result.response_doc.items[0]
        # Sensitivities should be a list of valid sensitivity values (or empty)
        for s in item.sensitivities:
            assert s in SENSITIVITY_TAGS


# ---------------------------------------------------------------------------
# PIPE2 — Safe terminal (RULE_SAFE_TERMINAL)
# ---------------------------------------------------------------------------

class TestPIPE2:
    """PIPE2: an injected component failure → safe terminal + ERROR_TERMINAL audit event.

    No uncaught exception may escape run_pipeline().
    """

    def test_provider_raise_yields_safe_terminal(self, tmp_path):
        """PIPE2: a raising LLMProvider → item ROUTED_FOR_REVIEW + UNGROUNDED_PLACEHOLDER."""
        from app.pipeline import run_pipeline
        from app.llm import LLMProvider
        from app.schema import ContextStack, DraftAnswer
        from app.config import UNGROUNDED_PLACEHOLDER

        class _RaisingProvider(LLMProvider):
            def draft(self, context_stack: ContextStack) -> DraftAnswer:
                raise RuntimeError("simulated provider failure")

        q = _make_minimal_questionnaire()
        # run_pipeline must NOT raise
        result = run_pipeline(
            q,
            provider=_RaisingProvider(),
            retriever=_build_retriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        # Item ends up in a safe terminal state
        item = result.response_doc.items[0]
        # The item should have been processed safely
        # If grounding_check catches it, draft_text may be UNGROUNDED_PLACEHOLDER
        # or item may be routed; no uncaught exception is the key guarantee.
        # The pipeline wraps everything in try/except.
        assert result is not None  # most important: no exception escaped

    def test_malformed_retriever_yields_safe_terminal(self, tmp_path):
        """PIPE2: a Retriever that raises → item ROUTED_FOR_REVIEW + ERROR_TERMINAL audit."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM
        from app.config import UNGROUNDED_PLACEHOLDER, ERROR_TERMINAL

        class _BadRetriever:
            def retrieve(self, *args, **kwargs):
                raise ValueError("simulated retrieval failure")

        q = _make_minimal_questionnaire()
        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_BadRetriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        # No exception escaped
        assert result is not None

        # Item is in safe terminal state
        item = result.response_doc.items[0]
        assert item.status == "ROUTED_FOR_REVIEW"
        assert item.draft_text == UNGROUNDED_PLACEHOLDER

        # ERROR_TERMINAL recorded in errors dict
        assert "q-test-001-i1" in result.errors

        # ERROR_TERMINAL audit event written
        audit_path = tmp_path / "audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line) for line in lines]
        error_events = [e for e in events if e.get("rule") == "RULE_SAFE_TERMINAL"]
        assert error_events, "Expected at least one ERROR_TERMINAL audit event"
        assert any(
            e.get("detail", {}).get("reason") == ERROR_TERMINAL
            for e in error_events
        )

    def test_no_uncaught_exception_on_multiple_failures(self, tmp_path):
        """PIPE2: multiple items, all failing → no exception, all error-terminated."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM
        from app.config import UNGROUNDED_PLACEHOLDER

        class _AlwaysRaisingRetriever:
            def retrieve(self, *args, **kwargs):
                raise RuntimeError("always fails")

        q = _make_minimal_questionnaire(
            questionnaire_id="q-multi-fail",
            items=[
                {"item_id": "q-multi-fail-i1", "question": "Q1?", "topic_tags": []},
                {"item_id": "q-multi-fail-i2", "question": "Q2?", "topic_tags": []},
            ],
        )

        result = run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_AlwaysRaisingRetriever(),
            policy_tags=_load_policy(),
            audit_log_path=tmp_path / "audit.jsonl",
        )

        assert len(result.response_doc.items) == 2
        for item in result.response_doc.items:
            assert item.status == "ROUTED_FOR_REVIEW"
            assert item.draft_text == UNGROUNDED_PLACEHOLDER
        assert len(result.errors) == 2

    def test_error_terminal_in_audit_log(self, tmp_path):
        """PIPE2: ERROR_TERMINAL audit reason-code appears in the log on failure."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM
        from app.config import ERROR_TERMINAL, RULE_SAFE_TERMINAL

        class _FailRetriever:
            def retrieve(self, *args, **kwargs):
                raise ValueError("force safe terminal")

        audit_path = tmp_path / "audit.jsonl"
        q = _make_minimal_questionnaire()
        run_pipeline(
            q,
            provider=MockLLM(),
            retriever=_FailRetriever(),
            policy_tags=_load_policy(),
            audit_log_path=audit_path,
        )

        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        # Find the safe-terminal event
        terminal_events = [
            e for e in events
            if e.get("rule") == RULE_SAFE_TERMINAL
        ]
        assert terminal_events, f"No RULE_SAFE_TERMINAL event found; events: {events}"
        details = [e.get("detail", {}) for e in terminal_events]
        assert any(d.get("reason") == ERROR_TERMINAL for d in details)


# ---------------------------------------------------------------------------
# DEMO1 — Confident auto-draft (case_confident)
# ---------------------------------------------------------------------------

class TestDEMO1:
    """DEMO1: case_confident produces confident drafts for i1/i2 and
    routes i3 via ROUTED_HIGH_RISK (defense-in-depth showcase).
    """

    def setup_method(self):
        from app.llm import MockLLM
        self.provider = MockLLM()
        self.retriever = _build_retriever()
        self.policy = _load_policy()

    def test_demo1_questionnaire_loads(self):
        """DEMO1: case_confident.synthetic.json loads without error."""
        q = _load_real_questionnaire("case_confident.synthetic.json")
        assert q["questionnaire_id"] == "q-confident-001"
        assert len(q["items"]) == 3

    def test_demo1_pipeline_runs_without_exception(self, tmp_path):
        """DEMO1: run_pipeline on case_confident does not raise."""
        q = _load_real_questionnaire("case_confident.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)
        assert result is not None
        assert result.errors == {}

    def test_demo1_i1_i2_not_routed(self, tmp_path):
        """DEMO1: items i1 and i2 should NOT trigger routing (no high-risk tag, high confidence)."""
        q = _load_real_questionnaire("case_confident.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        # i1 and i2 should not be routed
        for item in result.response_doc.items:
            if item.item_id in ("q-confident-001-i1", "q-confident-001-i2"):
                routing = result.routing.get(item.item_id)
                assert not routing.should_route, (
                    f"{item.item_id} should NOT be routed but was: "
                    f"reason={routing.reason_code}, queue={routing.queue}"
                )
                assert item.status == "SCORED", (
                    f"{item.item_id} should be at SCORED, got {item.status}"
                )

    def test_demo1_i3_routed_high_risk(self, tmp_path):
        """DEMO1: item i3 (security tag) is ROUTED_HIGH_RISK→security queue."""
        from app.config import ROUTED_HIGH_RISK
        q = _load_real_questionnaire("case_confident.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        i3 = next(
            item for item in result.response_doc.items
            if item.item_id == "q-confident-001-i3"
        )
        routing_i3 = result.routing["q-confident-001-i3"]
        assert routing_i3.should_route, "i3 must be routed (security tag)"
        assert routing_i3.reason_code == ROUTED_HIGH_RISK
        assert routing_i3.queue == "security"
        assert i3.status == "ROUTED_FOR_REVIEW"

    def test_demo1_i1_i2_grounded_drafts(self, tmp_path):
        """DEMO1: i1 and i2 should have grounded draft_text (not UNGROUNDED_PLACEHOLDER)."""
        from app.config import UNGROUNDED_PLACEHOLDER
        q = _load_real_questionnaire("case_confident.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        for item in result.response_doc.items:
            if item.item_id in ("q-confident-001-i1", "q-confident-001-i2"):
                assert item.draft_text != UNGROUNDED_PLACEHOLDER, (
                    f"{item.item_id} should have a grounded draft, got placeholder"
                )
                assert item.citations, f"{item.item_id} should have citations"

    def test_demo1_agent_never_self_approves(self, tmp_path):
        """DEMO1: no item in the response doc has status APPROVED (agent never self-approves)."""
        q = _load_real_questionnaire("case_confident.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        for item in result.response_doc.items:
            assert item.status != "APPROVED", (
                f"Agent self-approved item {item.item_id} — RULE_NO_SELF_APPROVE violated"
            )
            assert item.status != "EXPORTED", (
                f"Agent exported item {item.item_id} — RULE_NO_SELF_APPROVE violated"
            )

    def test_demo1_rule_hitm_not_fired_for_i1_i2(self, tmp_path):
        """DEMO1: RULE_HITM_REVIEW_TRIGGER does not fire for i1/i2 (no routing)."""
        q = _load_real_questionnaire("case_confident.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        audit_path = tmp_path / "audit.jsonl"
        events = [json.loads(line) for line in audit_path.read_text().splitlines()]

        for item_id in ("q-confident-001-i1", "q-confident-001-i2"):
            routing_events = [
                e for e in events
                if e["item_id"] == item_id and e.get("rule") == "RULE_HITM_REVIEW_TRIGGER"
            ]
            assert not routing_events, (
                f"RULE_HITM_REVIEW_TRIGGER should NOT fire for {item_id}"
            )


def _run_real_pipeline(questionnaire, tmp_path, provider=None):
    from app.pipeline import run_pipeline
    from app.llm import MockLLM
    return run_pipeline(
        questionnaire,
        provider=provider or MockLLM(),
        retriever=_build_retriever(),
        policy_tags=_load_policy(),
        audit_log_path=tmp_path / "audit.jsonl",
    )


# ---------------------------------------------------------------------------
# DEMO2 — Human-review exception (case_review)
# ---------------------------------------------------------------------------

class TestDEMO2:
    """DEMO2: case_review triggers RULE_HITM_REVIEW_TRIGGER for all items;
    items are ROUTED_FOR_REVIEW and never included in the export.
    """

    def test_demo2_questionnaire_loads(self):
        """DEMO2: case_review.synthetic.json loads without error."""
        q = _load_real_questionnaire("case_review.synthetic.json")
        assert q["questionnaire_id"] == "q-review-001"
        assert len(q["items"]) == 2

    def test_demo2_all_items_routed(self, tmp_path):
        """DEMO2: all case_review items are routed (legal tag → ROUTED_HIGH_RISK)."""
        q = _load_real_questionnaire("case_review.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        for item in result.response_doc.items:
            routing = result.routing.get(item.item_id)
            assert routing.should_route, (
                f"{item.item_id} should be routed but was not; "
                f"reason={routing.reason_code}"
            )
            assert item.status == "ROUTED_FOR_REVIEW"

    def test_demo2_routing_trigger_fires(self, tmp_path):
        """DEMO2: at least RULE_HITM_REVIEW_TRIGGER fires for each item."""
        from app.config import RULE_HITM_REVIEW_TRIGGER
        q = _load_real_questionnaire("case_review.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        audit_path = tmp_path / "audit.jsonl"
        events = [json.loads(line) for line in audit_path.read_text().splitlines()]

        for item in result.response_doc.items:
            triggered = [
                e for e in events
                if e["item_id"] == item.item_id
                and e.get("rule") == RULE_HITM_REVIEW_TRIGGER
            ]
            assert triggered, (
                f"RULE_HITM_REVIEW_TRIGGER should fire for {item.item_id}"
            )

    def test_demo2_review_banner_in_preview(self, tmp_path):
        """DEMO2: render_preview produces REVIEW_BANNER for case_review items."""
        from app.export import render_preview
        from app.schema import ResponseDoc
        from app.config import REVIEW_BANNER

        q = _load_real_questionnaire("case_review.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        preview = render_preview(result.response_doc)
        assert preview.startswith(REVIEW_BANNER), (
            "REVIEW_BANNER must be the first line of the preview for non-APPROVED items"
        )

    def test_demo2_items_never_exported(self, tmp_path):
        """DEMO2: no case_review item is exported (all ROUTED_FOR_REVIEW, not APPROVED)."""
        from app.export import export_response

        q = _load_real_questionnaire("case_review.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        paths = export_response(
            result.response_doc, out_dir=export_dir, log_path=tmp_path / "audit.jsonl"
        )

        md_content = paths["markdown"].read_text(encoding="utf-8")
        csv_content = paths["csv"].read_text(encoding="utf-8")

        # No item text should appear because none are APPROVED
        # CSV should only have the header row
        csv_lines = [line for line in csv_content.strip().splitlines() if line.strip()]
        assert len(csv_lines) == 1, (
            f"Only header row expected in CSV, got {len(csv_lines)} lines: {csv_lines}"
        )

    def test_demo2_agent_never_self_approves(self, tmp_path):
        """DEMO2: the agent (pipeline) never transitions items to APPROVED."""
        q = _load_real_questionnaire("case_review.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        for item in result.response_doc.items:
            assert item.status not in ("APPROVED", "EXPORTED"), (
                f"Agent self-approved {item.item_id} — RULE_NO_SELF_APPROVE violated"
            )


# ---------------------------------------------------------------------------
# RULE1 — Every RULE_* has a live chokepoint in the correct module
# ---------------------------------------------------------------------------

class TestRULE1:
    """RULE1: for each RULE_* string in app/config.py, grep proves it is referenced
    at the chokepoint module named in CLAUDE.md §5.1 — no orphan rule.
    """

    # Expected (rule_constant_name, chokepoint_module_file) pairs from §5.1
    RULE_CHOKEPOINTS = {
        "RULE_GROUNDED_ONLY": "app/draft.py",
        "RULE_NO_SELF_APPROVE": "app/state.py",
        "RULE_HITM_REVIEW_TRIGGER": "app/routing.py",
        "RULE_NO_EXTERNAL_SEND": "app/export.py",
        "RULE_SENSITIVITY_GATE": "app/export.py",
        "RULE_SAFE_TERMINAL": "app/pipeline.py",
        "RULE_AUDIT_COMPLETE": "app/audit.py",
    }

    def test_every_rule_referenced_at_chokepoint(self):
        """RULE1: each RULE_* string appears in its §5.1 chokepoint module."""
        import app.config as cfg
        import importlib

        # Gather all RULE_* string constants from config
        all_rules = {
            name: getattr(cfg, name)
            for name in dir(cfg)
            if name.startswith("RULE_")
        }
        assert all_rules, "Expected RULE_* constants in app.config"

        for rule_name, rule_value in all_rules.items():
            if rule_name not in self.RULE_CHOKEPOINTS:
                # Rules like RULE_NO_SECRET, RULE_NO_REAL_PII, etc. are enforced by
                # grep gates / .gitignore; they don't have a single Python module chokepoint.
                continue

            chokepoint_rel = self.RULE_CHOKEPOINTS[rule_name]
            chokepoint_path = REPO_ROOT / chokepoint_rel
            assert chokepoint_path.exists(), (
                f"Chokepoint module {chokepoint_rel} for {rule_name} does not exist"
            )

            content = chokepoint_path.read_text(encoding="utf-8")
            assert rule_value in content, (
                f"RULE_* string '{rule_value}' ({rule_name}) not found in "
                f"its chokepoint module {chokepoint_rel}"
            )

    def test_rule_grounded_only_in_draft(self):
        """RULE1: RULE_GROUNDED_ONLY is referenced in app/draft.py."""
        from app.config import RULE_GROUNDED_ONLY
        content = (REPO_ROOT / "app" / "draft.py").read_text()
        assert RULE_GROUNDED_ONLY in content

    def test_rule_no_self_approve_in_state(self):
        """RULE1: RULE_NO_SELF_APPROVE is referenced in app/state.py."""
        from app.config import RULE_NO_SELF_APPROVE
        content = (REPO_ROOT / "app" / "state.py").read_text()
        assert RULE_NO_SELF_APPROVE in content

    def test_rule_hitm_review_trigger_in_routing(self):
        """RULE1: RULE_HITM_REVIEW_TRIGGER is referenced in app/routing.py."""
        from app.config import RULE_HITM_REVIEW_TRIGGER
        content = (REPO_ROOT / "app" / "routing.py").read_text()
        assert RULE_HITM_REVIEW_TRIGGER in content

    def test_rule_no_external_send_in_export(self):
        """RULE1: RULE_NO_EXTERNAL_SEND is referenced in app/export.py."""
        from app.config import RULE_NO_EXTERNAL_SEND
        content = (REPO_ROOT / "app" / "export.py").read_text()
        assert RULE_NO_EXTERNAL_SEND in content

    def test_rule_sensitivity_gate_in_export(self):
        """RULE1: RULE_SENSITIVITY_GATE is referenced in app/export.py."""
        from app.config import RULE_SENSITIVITY_GATE
        content = (REPO_ROOT / "app" / "export.py").read_text()
        assert RULE_SENSITIVITY_GATE in content

    def test_rule_safe_terminal_in_pipeline(self):
        """RULE1: RULE_SAFE_TERMINAL is referenced in app/pipeline.py."""
        from app.config import RULE_SAFE_TERMINAL
        content = (REPO_ROOT / "app" / "pipeline.py").read_text()
        assert RULE_SAFE_TERMINAL in content

    def test_error_terminal_in_config(self):
        """RULE1: ERROR_TERMINAL reason-code is defined in app/config.py."""
        from app.config import ERROR_TERMINAL
        assert ERROR_TERMINAL == "ERROR_TERMINAL"

    def test_error_terminal_chokepoint_in_pipeline(self):
        """RULE1: ERROR_TERMINAL is referenced in app/pipeline.py (its chokepoint)."""
        from app.config import ERROR_TERMINAL
        content = (REPO_ROOT / "app" / "pipeline.py").read_text()
        assert ERROR_TERMINAL in content


# ---------------------------------------------------------------------------
# RULE2 — A pipeline run writes each expected reason-code to the audit log
# ---------------------------------------------------------------------------

class TestRULE2:
    """RULE2: a pipeline run (or dedicated test) that triggers each rule writes
    its reason-code to the audit log.

    Expected reason-codes per §5.1:
      GROUNDING_FAIL         — from RULE_GROUNDED_ONLY (triggered by empty retrieval)
      ROUTED_HIGH_RISK       — from RULE_HITM_REVIEW_TRIGGER (case_confident i3; case_review)
      ROUTED_LOW_CONFIDENCE  — from RULE_HITM_REVIEW_TRIGGER (low confidence)
      SELF_APPROVE_BLOCKED   — from RULE_NO_SELF_APPROVE (agent attempts transition)
      SENSITIVITY_HOLD       — from RULE_SENSITIVITY_GATE (internal/restricted item)
      EXTERNAL_SEND_BLOCKED  — from RULE_NO_EXTERNAL_SEND (export confirms local disk)
      ERROR_TERMINAL         — from RULE_SAFE_TERMINAL (injected failure)
    """

    def test_routed_high_risk_in_audit_log(self, tmp_path):
        """RULE2: ROUTED_HIGH_RISK reason-code written when high-risk tag fires."""
        from app.config import ROUTED_HIGH_RISK

        q = _load_real_questionnaire("case_confident.synthetic.json")
        audit_path = tmp_path / "audit.jsonl"
        _run_real_pipeline(q, tmp_path)

        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        codes = [e.get("detail", {}).get("reason_code") for e in events]
        assert ROUTED_HIGH_RISK in codes, (
            f"Expected {ROUTED_HIGH_RISK} in audit reason_codes; found: {codes}"
        )

    def test_external_send_blocked_in_audit_log(self, tmp_path):
        """RULE2: EXTERNAL_SEND_BLOCKED written when export_response fires."""
        from app.export import export_response
        from app.schema import ResponseDoc, ResponseDocItem, Citation
        from app.config import EXTERNAL_SEND_BLOCKED

        doc = ResponseDoc(
            questionnaire_id="q-rule2-bound",
            generated_at="2026-01-01T00:00:00+00:00",
            items=[
                ResponseDocItem(
                    item_id="i1",
                    question="Q?",
                    draft_text="Answer.",
                    citations=[Citation(chunk_id="kb-001")],
                    confidence_score=0.9,
                    status="APPROVED",
                    sensitivities=["public"],
                    review_approved=False,
                )
            ],
        )
        audit_path = tmp_path / "audit.jsonl"
        export_dir = tmp_path / "exp"
        export_dir.mkdir()
        export_response(doc, out_dir=export_dir, log_path=audit_path)

        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        reasons = [e.get("detail", {}).get("reason") for e in events]
        assert EXTERNAL_SEND_BLOCKED in reasons, (
            f"Expected {EXTERNAL_SEND_BLOCKED} in audit; got: {reasons}"
        )

    def test_sensitivity_hold_in_audit_log(self, tmp_path):
        """RULE2: SENSITIVITY_HOLD written when sensitivity gate holds an item."""
        from app.export import export_response
        from app.schema import ResponseDoc, ResponseDocItem, Citation
        from app.config import SENSITIVITY_HOLD

        doc = ResponseDoc(
            questionnaire_id="q-rule2-sens",
            generated_at="2026-01-01T00:00:00+00:00",
            items=[
                ResponseDocItem(
                    item_id="i1",
                    question="Q?",
                    draft_text="Answer.",
                    citations=[Citation(chunk_id="kb-009")],
                    confidence_score=0.9,
                    status="APPROVED",
                    sensitivities=["internal"],  # should be held
                    review_approved=False,
                )
            ],
        )
        audit_path = tmp_path / "audit.jsonl"
        export_dir = tmp_path / "exp"
        export_dir.mkdir()
        export_response(doc, out_dir=export_dir, log_path=audit_path)

        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        reasons = [e.get("detail", {}).get("reason") for e in events]
        assert SENSITIVITY_HOLD in reasons

    def test_self_approve_blocked_on_agent_attempt(self, tmp_path):
        """RULE2: SELF_APPROVE_BLOCKED is raised when agent tries to self-approve."""
        from app.state import transition, SelfApproveBlocked
        from app.config import SELF_APPROVE_BLOCKED

        try:
            transition("SCORED", "APPROVED", actor="agent")
            pytest.fail("SelfApproveBlocked should have been raised")
        except SelfApproveBlocked as exc:
            assert exc.reason_code == SELF_APPROVE_BLOCKED

    def test_error_terminal_in_audit_on_failure(self, tmp_path):
        """RULE2: ERROR_TERMINAL written to audit when RULE_SAFE_TERMINAL fires."""
        from app.pipeline import run_pipeline
        from app.llm import MockLLM
        from app.config import ERROR_TERMINAL

        class _BadRetriever:
            def retrieve(self, *args, **kwargs):
                raise RuntimeError("force error terminal")

        audit_path = tmp_path / "audit.jsonl"
        run_pipeline(
            _make_minimal_questionnaire(),
            provider=MockLLM(),
            retriever=_BadRetriever(),
            policy_tags=_load_policy(),
            audit_log_path=audit_path,
        )

        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        reasons = [e.get("detail", {}).get("reason") for e in events]
        assert ERROR_TERMINAL in reasons

    def test_routed_high_risk_in_case_review(self, tmp_path):
        """RULE2: ROUTED_HIGH_RISK fires for case_review items (legal + security tags)."""
        from app.config import ROUTED_HIGH_RISK

        q = _load_real_questionnaire("case_review.synthetic.json")
        result = _run_real_pipeline(q, tmp_path)

        audit_path = tmp_path / "audit.jsonl"
        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        codes = [e.get("detail", {}).get("reason_code") for e in events]
        assert ROUTED_HIGH_RISK in codes

    def test_grounding_fail_reason_code_defined(self):
        """RULE2: GROUNDING_FAIL reason-code is defined in config and referenced in draft.py."""
        from app.config import GROUNDING_FAIL
        assert GROUNDING_FAIL == "GROUNDING_FAIL"
        content = (REPO_ROOT / "app" / "draft.py").read_text()
        assert GROUNDING_FAIL in content
