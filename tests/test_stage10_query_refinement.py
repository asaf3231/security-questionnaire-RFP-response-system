"""
tests/test_stage10_query_refinement.py — Stage 10 (Intelligent Query Refinement) suite.

PURELY ADDITIVE (honors RULE_GRADED_ARTIFACT_LOCK / META-LOCK): modifies no existing
test, fixture, or app module, and changes no graded contract. Fully offline and
deterministic (MockLLM identity + seeded BM25, no network).

Covers the Stage 10 QA IDs:
  QREF1 — strip_thinking_block deterministically removes <thinking> reasoning
  QREF2 — refine_query: offline identity (determinism preserved) + safe fallbacks
  QREF3 — pipeline injects QUERY_REFINEMENT before retrieve + audits original/optimized
  DRAFT-COT1 — the live draft prompt carries the ORIGINAL question + the <thinking> directive
               (regression for the defect: the question used to be absent from the prompt)
  DRAFT-COT2 — ClaudeLLM.draft strips <thinking> before the gate/export sees the answer;
               the offline MockLLM path never emits <thinking>

The ClaudeLLM tests fake ONLY the external boundary (the Anthropic client) with a
behaviour-faithful non-constant stub — the real _build_prompt / draft / strip internal
path runs (META-REALPATH).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import UNGROUNDED_PLACEHOLDER
from app.context_stack import assemble_context
from app.kb import load_kb, load_policy_tags, load_questionnaire
from app.llm import (
    ClaudeLLM,
    LLMProvider,
    MockLLM,
    _REFINE_DIRECTIVE,
)
from app.pipeline import run_pipeline
from app.query_optimizer import refine_query, strip_thinking_block
from app.retrieval import Retriever
from app.schema import ContextStack, QuestionnaireItem

_REPO = Path(__file__).resolve().parent.parent
_CONFIDENT_Q = _REPO / "data" / "questionnaires" / "case_confident.synthetic.json"


def _first_item() -> QuestionnaireItem:
    q = load_questionnaire(_CONFIDENT_Q)
    return q["items"][0]


def _stack_for(item: QuestionnaireItem) -> ContextStack:
    hits = Retriever(load_kb()).retrieve(item.question, topic_tags=item.topic_tags or None)
    return assemble_context(item, hits, item_number=1, total_items=3)


# ---------------------------------------------------------------------------
# Behaviour-faithful fakes (only the external boundaries — provider / client)
# ---------------------------------------------------------------------------

class _FakeRefineProvider(LLMProvider):
    """LLMProvider whose refine_query returns a configured raw string (drives QREF2)."""

    def __init__(self, raw: str, *, raise_it: bool = False) -> None:
        self._raw = raw
        self._raise = raise_it

    def draft(self, context_stack):  # not exercised in QREF2 tests
        return MockLLM().draft(context_stack)

    def refine_query(self, question: str) -> str:
        if self._raise:
            raise RuntimeError("boom")
        return self._raw


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **kwargs):  # mirrors anthropic client.messages.create
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


# ---------------------------------------------------------------------------
# QREF1 — strip_thinking_block
# ---------------------------------------------------------------------------

class TestStripThinkingBlock:
    def test_strips_wellformed_block(self):
        assert strip_thinking_block("<thinking>reason here</thinking> encryption AES TLS") == "encryption AES TLS"

    def test_dangling_open_tag_strips_to_empty(self):
        # No closing tag → everything from the open tag is dropped (safe → caller falls back)
        assert strip_thinking_block("<thinking>no close tag at all") == ""

    def test_no_tags_passthrough(self):
        assert strip_thinking_block("just keywords here") == "just keywords here"

    def test_case_insensitive_and_multiline(self):
        text = "<THINKING>\nline one\nline two\n</THINKING>\nencryption keys"
        assert strip_thinking_block(text) == "encryption keys"

    def test_multiple_blocks_all_removed(self):
        text = "<thinking>a</thinking> keep1 <thinking>b</thinking> keep2"
        out = strip_thinking_block(text)
        assert "<thinking>" not in out and "keep1" in out and "keep2" in out

    def test_malformed_close_tag_does_not_eat_answer(self):
        # A close tag with trailing chars (`</thinking foo>`) must still close the block —
        # otherwise the open-to-end fallback would delete the real cited answer.
        out = strip_thinking_block("<thinking>reason</thinking foo> We encrypt at rest [kb-001].")
        assert out == "We encrypt at rest [kb-001]."

    def test_open_tag_with_attributes(self):
        out = strip_thinking_block('<thinking model="x">reason</thinking> encryption AES')
        assert out == "encryption AES"

    def test_empty_input(self):
        assert strip_thinking_block("") == ""

    # --- ADDED 2026-06-28: nested-tag regression (the prior non-greedy regex leaked the
    # outer block's tail; the depth-aware scan must drop the WHOLE outer block) ---
    def test_nested_blocks_outer_fully_removed(self):
        out = strip_thinking_block("<thinking>a<thinking>b</thinking>c</thinking> answer")
        assert out == "answer"

    def test_nested_blocks_no_tail_leak(self):
        # The reported leak: inner close ended the non-greedy match early, leaking `c`/`d`.
        out = strip_thinking_block("<thinking>a<thinking>b</thinking> c</thinking>d")
        assert "<thinking>" not in out and "b" not in out and "c" not in out
        assert out == "d"

    def test_nested_keeps_content_between_separate_blocks(self):
        # Nesting must NOT regress the separate-blocks behavior (content between is kept).
        out = strip_thinking_block(
            "<thinking>x<thinking>y</thinking>z</thinking> keep1 <thinking>q</thinking> keep2"
        )
        assert "<thinking>" not in out and "keep1" in out and "keep2" in out
        assert "y" not in out and "z" not in out

    def test_stray_close_tag_keeps_surrounding_text(self):
        out = strip_thinking_block("encryption</thinking> keys")
        assert "</thinking>" not in out and "encryption" in out and "keys" in out

    def test_tag_with_no_surrounding_whitespace_does_not_fuse_tokens(self):
        # REGRESSION (code-review 2026-06-28): a removed block/tag between two words with NO
        # surrounding whitespace must act as a token boundary, else BM25 gets a fused garbage
        # token. `AES<thinking>r</thinking>TLS` must become `AES TLS`, not `AESTLS`.
        assert strip_thinking_block("AES<thinking>r</thinking>TLS") == "AES TLS"
        assert strip_thinking_block("AES</thinking>TLS") == "AES TLS"


# ---------------------------------------------------------------------------
# QREF2 — refine_query: offline identity + safe fallbacks
# ---------------------------------------------------------------------------

class TestRefineQueryWrapper:
    def test_mock_provider_is_identity(self):
        """Offline determinism: MockLLM inherits the identity default → query unchanged."""
        q = "Does your platform encrypt data at rest?"
        assert MockLLM().refine_query(q) == q
        assert refine_query(q, provider=MockLLM()) == q

    def test_strips_thinking_keeps_keywords(self):
        prov = _FakeRefineProvider("<thinking>concepts</thinking> encryption AES TLS rest")
        assert refine_query("how do you encrypt?", provider=prov) == "encryption AES TLS rest"

    def test_fallback_when_only_thinking(self):
        prov = _FakeRefineProvider("<thinking>all reasoning, no keywords</thinking>")
        q = "original question text"
        assert refine_query(q, provider=prov) == q

    def test_fallback_when_empty(self):
        q = "original question text"
        assert refine_query(q, provider=_FakeRefineProvider("")) == q

    def test_fallback_when_no_alphanumeric(self):
        q = "original question text"
        assert refine_query(q, provider=_FakeRefineProvider("!!! ??? ...")) == q

    def test_fallback_on_provider_exception(self):
        q = "original question text"
        assert refine_query(q, provider=_FakeRefineProvider("x", raise_it=True)) == q

    def test_bounds_runaway_length(self):
        prov = _FakeRefineProvider("word " * 1000)
        out = refine_query("q", provider=prov)
        assert len(out) <= 512


# ---------------------------------------------------------------------------
# DRAFT-COT1 — the original question reaches the draft prompt (defect regression)
# ---------------------------------------------------------------------------

class TestContextStackQuestion:
    def test_assemble_context_carries_question(self):
        item = _first_item()
        assert _stack_for(item).question == item.question

    def test_build_prompt_includes_original_question(self):
        """REGRESSION: the item question used to be absent from the live prompt."""
        item = _first_item()
        prompt = ClaudeLLM()._build_prompt(_stack_for(item))
        assert item.question in prompt

    def test_build_prompt_requests_inline_citations_answer_only(self):
        # SPEC CHANGE (two-key authorized 2026-06-28, Asaf): the draft prompt NO LONGER
        # injects a <thinking> reasoning scaffold. Live evidence (redteam/LIVE_RUN_FINDINGS
        # .nothinking 40/50 grounded vs .stage10 25/100 WITH the scaffold) shows the scaffold
        # makes the model emit reasoning prose and drop inline [chunk_id] citations, tanking
        # live grounding. The draft now requests inline citations + answer-only output.
        # (Superseded test: test_build_prompt_includes_thinking_directive.)
        prompt = ClaudeLLM()._build_prompt(_stack_for(_first_item()))
        assert "<thinking>" not in prompt
        assert "[chunk_id]" in prompt
        assert "ONLY the answer" in prompt

    def test_context_stack_backward_compatible_default(self):
        """A pre-Stage-10 construction without question still validates (default '')."""
        cs = ContextStack(instruction="i", retrieval=[], constraint="c", state="s")
        assert cs.question == ""


# ---------------------------------------------------------------------------
# DRAFT-COT2 — ClaudeLLM.draft strips <thinking>; MockLLM never emits it
# ---------------------------------------------------------------------------

class TestDraftThinkingStrip:
    def test_claude_draft_strips_thinking_keeps_citation(self, monkeypatch):
        item = _first_item()
        stack = _stack_for(item)
        cited = stack.retrieval[0].split("]")[0].lstrip("[")  # a real retrieved chunk_id
        fake_text = f"<thinking>map {cited} → answer; no conflicts</thinking> We encrypt at rest [{cited}]."
        monkeypatch.setattr("app.config._get_claude", lambda: _FakeClient(fake_text))

        draft = ClaudeLLM().draft(stack)
        assert "<thinking>" not in draft.text
        assert draft.text == f"We encrypt at rest [{cited}]."
        assert any(c.chunk_id == cited for c in draft.citations)

    def test_claude_draft_thinking_only_degrades_to_placeholder(self, monkeypatch):
        stack = _stack_for(_first_item())
        monkeypatch.setattr("app.config._get_claude", lambda: _FakeClient("<thinking>only reasoning</thinking>"))
        draft = ClaudeLLM().draft(stack)
        assert draft.text == UNGROUNDED_PLACEHOLDER
        assert draft.citations == []

    def test_mock_draft_never_emits_thinking(self):
        draft = MockLLM().draft(_stack_for(_first_item()))
        assert "<thinking>" not in draft.text


# ---------------------------------------------------------------------------
# QREF3 — pipeline injects + audits the refinement stage
# ---------------------------------------------------------------------------

class TestPipelineRefinement:
    def _run(self, tmp_path, provider):
        q = load_questionnaire(_CONFIDENT_Q)
        log = tmp_path / "audit.jsonl"
        run_pipeline(
            q,
            provider=provider,
            retriever=Retriever(load_kb()),
            policy_tags=load_policy_tags(),
            audit_log_path=log,
        )
        events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        return [e for e in events if (e.get("detail") or {}).get("tool") == "refine_query"]

    def test_pipeline_emits_refine_audit_event(self, tmp_path):
        refine_events = self._run(tmp_path, MockLLM())
        assert refine_events, "pipeline must emit a refine_query audit event per item"
        for e in refine_events:
            d = e["detail"]
            assert "original" in d and "optimized" in d

    def test_offline_refine_is_identity(self, tmp_path):
        """MockLLM path: optimized == original (deterministic retrieval preserved)."""
        refine_events = self._run(tmp_path, MockLLM())
        for e in refine_events:
            assert e["detail"]["optimized"] == e["detail"]["original"]

    def test_refined_query_recorded_when_provider_rewrites(self, tmp_path):
        """A rewriting provider's optimized query is what gets audited (real wiring)."""
        prov = _FakeRefineProvider("encryption AES TLS rest transit")
        refine_events = self._run(tmp_path, prov)
        assert refine_events
        assert all(e["detail"]["optimized"] == "encryption AES TLS rest transit" for e in refine_events)


# ---------------------------------------------------------------------------
# Grep-enforceable prompt-scaffold constants (DRAFT-COT2 / META spirit)
# ---------------------------------------------------------------------------

class TestPromptScaffoldConstants:
    def test_refine_directive_shape(self):
        assert "<thinking>" in _REFINE_DIRECTIVE
        assert "optimized search query" in _REFINE_DIRECTIVE
        assert "synonyms" in _REFINE_DIRECTIVE

    # RETIRED (two-key authorized 2026-06-28, Asaf): test_draft_directive_has_three_checks.
    # The _DRAFT_THINKING_DIRECTIVE constant was removed from app/llm.py (the draft no longer
    # uses a <thinking> scaffold — see the SPEC CHANGE note in TestContextStackQuestion). The
    # refine-query <thinking> path (above) and the DEFENSIVE strip in ClaudeLLM.draft
    # (TestDraftThinkingStrip) remain — the model may still emit reasoning even when not asked.
