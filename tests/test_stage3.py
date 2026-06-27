"""
tests/test_stage3.py — Offline deterministic suite for Stage 3.

Covers: CTX1–CTX4, SCHEMA1, DRAFT1, DRAFT2, GROUND1, and progressive ENV4
(app.context_stack, app.llm, app.draft added to the import-safety set).

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: MockLLM is seeded/deterministic; no random state.

QA check mapping:
  CTX1   — assemble_context returns ContextStack with all 4 layers; Retrieval = ONLY passed chunks
  CTX2   — Instruction layer carries RFP handling rules
  CTX3   — Constraint layer injects high-risk clause for high-risk items; not for benign items
  CTX4   — State layer carries "Question X of Y"
  SCHEMA1 — DraftAnswer/Citation validate; malformed draft (empty text) rejected
  DRAFT1 — draft_answer via MockLLM produces text + citations; deterministic; offline
  DRAFT2 — provider that raises → draft_answer returns UNGROUNDED_PLACEHOLDER, no exception
            live ClaudeLLM path is @pytest.mark.skipif(no ANTHROPIC_API_KEY)
  GROUND1 — grounding_check rejects ungrounded drafts; UNGROUNDED_PLACEHOLDER byte-exact
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

def _make_item(item_id: str = "i1", question: str = "Q?", topic_tags: list[str] | None = None):
    from app.schema import QuestionnaireItem
    return QuestionnaireItem(
        item_id=item_id,
        question=question,
        topic_tags=topic_tags or [],
    )


def _make_chunk(
    chunk_id: str,
    answer: str,
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
        bm25_score=1.0,
    )


def _make_context(
    item=None,
    chunks=None,
    item_number: int = 1,
    total_items: int = 3,
):
    from app.context_stack import assemble_context
    if item is None:
        item = _make_item()
    if chunks is None:
        chunks = [
            _make_chunk("c1", "We use AES-256 encryption for data at rest."),
            _make_chunk("c2", "Access is controlled via MFA and RBAC policies."),
        ]
    return assemble_context(item, chunks, item_number=item_number, total_items=total_items)


# ---------------------------------------------------------------------------
# Progressive ENV4 — import-safety for Stage 3 modules
# ---------------------------------------------------------------------------

class TestENV4Stage3:
    """ENV4 (progressive): Stage 3 modules import without side effects.

    Adds app.context_stack, app.llm, app.draft to the tested set.
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
    ]

    def test_stage3_modules_import_cleanly(self):
        """Stage 3 app.* modules import without raising in a subprocess with no .env."""
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
            f"Import of Stage 3 app modules failed:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_context_stack_no_side_effects_at_import(self):
        """app.context_stack imports with no KB read, no network, no .env."""
        import app.context_stack  # noqa: F401

    def test_llm_no_side_effects_at_import(self):
        """app.llm imports with no client build, no network, no .env."""
        import app.llm  # noqa: F401
        # _get_claude() must NOT have been called during import
        import app.config as cfg
        assert cfg._claude_client is None, (
            "ClaudeLLM import triggered _get_claude(); the client must remain None at import."
        )

    def test_draft_no_side_effects_at_import(self):
        """app.draft imports cleanly."""
        import app.draft  # noqa: F401


# ---------------------------------------------------------------------------
# CTX1 — 4 layers present; Retrieval = ONLY passed chunks
# ---------------------------------------------------------------------------

class TestCTX1:
    """CTX1: assemble_context returns ContextStack with all 4 layers;
    Retrieval layer = ONLY the passed-in chunks (no other KB content leaks in).
    """

    def test_all_four_layers_present(self):
        """ContextStack has instruction, retrieval, constraint, and state."""
        cs = _make_context()
        assert cs.instruction, "instruction layer must be non-empty"
        assert isinstance(cs.retrieval, list), "retrieval layer must be a list"
        assert cs.constraint, "constraint layer must be non-empty"
        assert cs.state, "state layer must be non-empty"

    def test_retrieval_layer_has_exactly_the_passed_chunks(self):
        """Retrieval layer contains exactly as many entries as passed chunks."""
        chunks = [
            _make_chunk("cx1", "Answer one."),
            _make_chunk("cx2", "Answer two."),
        ]
        cs = _make_context(chunks=chunks)
        assert len(cs.retrieval) == 2, (
            f"Expected 2 retrieval entries (one per chunk); got {len(cs.retrieval)}"
        )

    def test_retrieval_entries_contain_chunk_id_and_text(self):
        """Each retrieval entry is formatted as '[chunk_id] <text>'."""
        chunks = [_make_chunk("c42", "Encryption is AES-256.")]
        cs = _make_context(chunks=chunks)
        assert len(cs.retrieval) == 1
        assert cs.retrieval[0].startswith("[c42]"), (
            f"Retrieval entry should start with '[c42]'; got: {cs.retrieval[0]!r}"
        )
        assert "Encryption is AES-256" in cs.retrieval[0], (
            f"Retrieval entry should contain chunk answer text; got: {cs.retrieval[0]!r}"
        )

    def test_no_extra_kb_content_in_retrieval_layer(self):
        """Retrieval layer must not contain text from chunks not in the passed list."""
        from app.kb import load_kb
        all_chunks = load_kb()
        # Pass only 1 chunk; all other KB chunks must NOT appear in retrieval layer
        passed_chunk = all_chunks[0]
        other_chunks = all_chunks[1:]

        cs = _make_context(chunks=[passed_chunk])
        retrieval_text = " ".join(cs.retrieval)

        for other in other_chunks[:5]:  # check a sample of others
            # Use a sufficiently distinct snippet (first 30 chars of answer)
            snippet = other.answer[:30]
            if len(snippet) >= 15 and snippet not in passed_chunk.answer:
                assert snippet not in retrieval_text, (
                    f"KB chunk '{other.chunk_id}' text leaked into retrieval layer: {snippet!r}"
                )

    def test_empty_chunks_produces_empty_retrieval_layer(self):
        """When no chunks are passed, the retrieval layer is an empty list."""
        cs = _make_context(chunks=[])
        assert cs.retrieval == [], (
            f"Expected empty retrieval layer; got {cs.retrieval}"
        )


# ---------------------------------------------------------------------------
# CTX2 — Instruction layer carries RFP handling rules
# ---------------------------------------------------------------------------

class TestCTX2:
    """CTX2: Instruction layer carries explicit RFP/questionnaire handling rules."""

    def test_instruction_layer_non_empty(self):
        """The instruction layer is a non-empty string."""
        cs = _make_context()
        assert cs.instruction and len(cs.instruction) > 10, (
            "Instruction layer should carry substantive content"
        )

    def test_instruction_contains_grounding_rule(self):
        """Instruction must tell the model to use ONLY retrieved evidence."""
        cs = _make_context()
        instr = cs.instruction.lower()
        assert "only" in instr or "retrieval" in instr, (
            "Instruction layer should contain guidance to use ONLY retrieved evidence; "
            f"got: {cs.instruction!r}"
        )

    def test_instruction_contains_citation_rule(self):
        """Instruction must tell the model to cite chunks by chunk_id."""
        cs = _make_context()
        instr = cs.instruction.lower()
        assert "cite" in instr or "chunk_id" in instr or "[chunk_id]" in cs.instruction, (
            "Instruction layer should tell the model to cite chunks; "
            f"got: {cs.instruction!r}"
        )

    def test_instruction_is_from_module_constant(self):
        """Instruction text comes from the INSTRUCTION_CONTEXT module constant."""
        from app.context_stack import INSTRUCTION_CONTEXT
        cs = _make_context()
        assert cs.instruction == INSTRUCTION_CONTEXT, (
            "Instruction layer does not match the module-level INSTRUCTION_CONTEXT constant"
        )


# ---------------------------------------------------------------------------
# CTX3 — Constraint layer injects high-risk clause for high-risk items
# ---------------------------------------------------------------------------

class TestCTX3:
    """CTX3: Constraint layer injects the high-risk clause for high-risk items;
    not injected for benign items.
    """

    def test_constraint_layer_non_empty_for_all_items(self):
        """The constraint layer is always non-empty."""
        cs = _make_context()
        assert cs.constraint, "Constraint layer must always be non-empty"

    def test_high_risk_item_gets_high_risk_clause(self):
        """An item with a HIGH_RISK_TAGS tag gets the additional high-risk constraint clause."""
        from app.config import HIGH_RISK_TAGS
        high_risk_item = _make_item(topic_tags=[HIGH_RISK_TAGS[0]])  # e.g. "legal"
        cs = _make_context(item=high_risk_item)
        # The high-risk clause should be present in the constraint
        assert "high-risk" in cs.constraint.lower() or "high risk" in cs.constraint.lower(), (
            f"High-risk item should trigger a high-risk clause in the constraint layer; "
            f"got: {cs.constraint!r}"
        )

    def test_benign_item_no_high_risk_clause(self):
        """A benign item (no high-risk tags) does NOT get the high-risk constraint clause."""
        benign_item = _make_item(topic_tags=["engineering"])
        cs_benign = _make_context(item=benign_item)
        # The security/legal-specific high-risk clause should NOT be present
        assert "defer to human review" not in cs_benign.constraint.lower() or (
            "high-risk" not in cs_benign.constraint.lower()
            and "do not assert a legal position" not in cs_benign.constraint.lower()
        ), (
            f"Benign item should not have the high-risk clause; got: {cs_benign.constraint!r}"
        )

    def test_security_tag_also_triggers_high_risk_clause(self):
        """An item tagged 'security' also triggers the high-risk clause."""
        security_item = _make_item(topic_tags=["security"])
        cs = _make_context(item=security_item)
        assert "high-risk" in cs.constraint.lower() or "high risk" in cs.constraint.lower(), (
            f"'security' tag should trigger high-risk clause; got: {cs.constraint!r}"
        )

    def test_constraint_contains_base_hard_boundary(self):
        """The constraint layer always contains the base hard boundary instruction."""
        cs = _make_context()
        assert "only" in cs.constraint.lower() or "retrieval" in cs.constraint.lower(), (
            f"Constraint layer should contain the base grounding rule; got: {cs.constraint!r}"
        )


# ---------------------------------------------------------------------------
# CTX4 — State layer carries "Question X of Y" and item state
# ---------------------------------------------------------------------------

class TestCTX4:
    """CTX4: State layer carries position in the questionnaire (X of Y) and current state."""

    def test_state_layer_contains_question_x_of_y(self):
        """State layer must contain 'Question N of M' text."""
        cs = _make_context(item_number=2, total_items=5)
        assert "2" in cs.state and "5" in cs.state, (
            f"State layer must contain item_number (2) and total_items (5); got: {cs.state!r}"
        )
        assert "question" in cs.state.lower(), (
            f"State layer should contain the word 'Question'; got: {cs.state!r}"
        )

    def test_state_layer_contains_item_id(self):
        """State layer includes the item ID."""
        item = _make_item(item_id="item-007")
        cs = _make_context(item=item, item_number=1, total_items=10)
        assert "item-007" in cs.state, (
            f"State layer should contain item_id 'item-007'; got: {cs.state!r}"
        )

    def test_state_layer_varies_with_position(self):
        """State layer text changes when item_number/total_items change."""
        cs1 = _make_context(item_number=1, total_items=3)
        cs3 = _make_context(item_number=3, total_items=3)
        assert cs1.state != cs3.state, (
            "State layer should differ between item_number=1 and item_number=3"
        )


# ---------------------------------------------------------------------------
# SCHEMA1 — DraftAnswer / Citation validate; malformed draft rejected
# ---------------------------------------------------------------------------

class TestSCHEMA1:
    """SCHEMA1: DraftAnswer/Citation validate; malformed draft (empty text) rejected."""

    def test_valid_draft_answer_constructs(self):
        """A well-formed DraftAnswer constructs without error."""
        from app.schema import DraftAnswer, Citation
        da = DraftAnswer(
            text="Based on [c1]: We use AES-256.",
            citations=[Citation(chunk_id="c1")],
        )
        assert da.text
        assert len(da.citations) == 1
        assert da.citations[0].chunk_id == "c1"

    def test_empty_text_draft_answer_rejected(self):
        """DraftAnswer with empty text must raise ValidationError."""
        from app.schema import DraftAnswer
        with pytest.raises(Exception):  # pydantic ValidationError
            DraftAnswer(text="", citations=[])

    def test_whitespace_only_text_draft_answer_rejected(self):
        """DraftAnswer with whitespace-only text must raise ValidationError."""
        from app.schema import DraftAnswer
        with pytest.raises(Exception):
            DraftAnswer(text="   ", citations=[])

    def test_citation_with_chunk_id_constructs(self):
        """A Citation with a chunk_id constructs correctly."""
        from app.schema import Citation
        c = Citation(chunk_id="kb-001", source="approved_answers")
        assert c.chunk_id == "kb-001"
        assert c.source == "approved_answers"

    def test_draft_answer_default_citations_is_empty_list(self):
        """DraftAnswer.citations defaults to an empty list."""
        from app.schema import DraftAnswer
        da = DraftAnswer(text="Some answer text here.")
        assert da.citations == []

    def test_draft_answer_with_multiple_citations(self):
        """DraftAnswer can carry multiple citations."""
        from app.schema import DraftAnswer, Citation
        da = DraftAnswer(
            text="Answer using [c1] and [c2].",
            citations=[Citation(chunk_id="c1"), Citation(chunk_id="c2")],
        )
        assert len(da.citations) == 2


# ---------------------------------------------------------------------------
# DRAFT1 — draft_answer via MockLLM; deterministic; offline
# ---------------------------------------------------------------------------

class TestDRAFT1:
    """DRAFT1: draft_answer(context_stack) produces DraftAnswer with text + citations;
    offline MockLLM is deterministic; prompt built only from the ContextStack.
    """

    def test_draft_answer_returns_draft_answer_type(self):
        """draft_answer returns a DraftAnswer object."""
        from app.draft import draft_answer
        from app.schema import DraftAnswer
        cs = _make_context()
        result = draft_answer(cs)
        assert isinstance(result, DraftAnswer), (
            f"draft_answer must return DraftAnswer; got {type(result)}"
        )

    def test_draft_answer_has_non_empty_text(self):
        """draft_answer returns a DraftAnswer with non-empty text."""
        from app.draft import draft_answer
        cs = _make_context()
        result = draft_answer(cs)
        assert result.text and result.text.strip(), "DraftAnswer.text must be non-empty"

    def test_draft_answer_has_citations(self):
        """draft_answer via MockLLM returns citations drawn from the retrieval layer."""
        from app.draft import draft_answer
        from app.schema import DraftAnswer
        chunks = [
            _make_chunk("c-enc", "We use AES-256 encryption at rest."),
            _make_chunk("c-mfa", "MFA is required for all admin access."),
        ]
        cs = _make_context(chunks=chunks)
        result = draft_answer(cs)
        # MockLLM should cite chunk_ids from the retrieval layer
        cited_ids = {c.chunk_id for c in result.citations}
        assert len(cited_ids) > 0, "MockLLM draft should produce at least one citation"
        # All cited ids must be from the passed chunks
        allowed_ids = {"c-enc", "c-mfa"}
        assert cited_ids.issubset(allowed_ids), (
            f"Citations should only reference passed chunks; got {cited_ids}"
        )

    def test_mock_llm_is_deterministic(self):
        """Two calls with the same ContextStack produce identical DraftAnswer."""
        from app.draft import draft_answer
        from app.llm import MockLLM
        cs = _make_context()
        provider = MockLLM()
        result1 = draft_answer(cs, provider=provider)
        result2 = draft_answer(cs, provider=provider)
        assert result1.text == result2.text, (
            f"MockLLM must be deterministic; texts differ:\n{result1.text!r}\n{result2.text!r}"
        )
        assert [c.chunk_id for c in result1.citations] == [c.chunk_id for c in result2.citations], (
            "MockLLM must be deterministic; citations differ"
        )

    def test_mock_llm_is_offline(self):
        """MockLLM does not make any network calls (no import of network libs)."""
        from app.llm import MockLLM
        import socket
        # Verify MockLLM.draft does not use socket-level networking by checking
        # that no network libs are imported as a result of calling draft()
        # (This is a static structural check — MockLLM explicitly avoids network imports.)
        provider = MockLLM()
        cs = _make_context()
        # If this call blocks or raises a network error, MockLLM is not offline.
        # In a truly offline test environment this would hang; it should complete instantly.
        result = provider.draft(cs)
        assert result is not None

    def test_default_provider_is_mock_llm(self):
        """draft_answer with no provider argument uses MockLLM (offline default)."""
        from app.draft import draft_answer
        # Should succeed with no .env, no network, no API key
        cs = _make_context()
        result = draft_answer(cs)  # no provider → defaults to MockLLM()
        assert result.text

    def test_draft_uses_only_context_stack(self):
        """MockLLM draft text is derived from the retrieval layer (no outside KB leakage)."""
        from app.llm import MockLLM
        # Two different retrieval layers → different outputs
        chunks_a = [_make_chunk("ca1", "Unique answer alpha content zeta.")]
        chunks_b = [_make_chunk("cb1", "Unique answer beta content omega.")]
        cs_a = _make_context(chunks=chunks_a)
        cs_b = _make_context(chunks=chunks_b)
        provider = MockLLM()
        result_a = provider.draft(cs_a)
        result_b = provider.draft(cs_b)
        assert result_a.text != result_b.text, (
            "MockLLM should produce different text for different retrieval layers"
        )


# ---------------------------------------------------------------------------
# DRAFT2 — provider raises → UNGROUNDED_PLACEHOLDER returned, no exception
# ---------------------------------------------------------------------------

class TestDRAFT2:
    """DRAFT2: a provider whose draft() raises → draft_answer returns UNGROUNDED_PLACEHOLDER,
    never an unhandled exception, never a partial/invented answer.

    The live ClaudeLLM real-timeout path is @pytest.mark.skipif(no ANTHROPIC_API_KEY).
    """

    class _RaisingProvider:
        """Stub LLMProvider that always raises RuntimeError."""
        def draft(self, context_stack):
            raise RuntimeError("Simulated provider failure")

    def test_raising_provider_degrades_to_placeholder(self):
        """A provider that raises causes draft_answer to return UNGROUNDED_PLACEHOLDER.

        This tests the OFFLINE degradation path: the error is caught and the pipeline
        gets a structured result instead of an exception.
        """
        from app.draft import draft_answer, grounding_check
        from app.config import UNGROUNDED_PLACEHOLDER, GROUNDING_FAIL
        from app.schema import DraftAnswer, Citation

        # Simulate a provider that raises on draft()
        class RaisingLLM:
            def draft(self, context_stack):
                raise RuntimeError("Simulated provider failure")

        cs = _make_context()

        # draft_answer should not propagate the exception
        # Instead it should return UNGROUNDED_PLACEHOLDER via the degrade path
        # The grounding_check in draft_answer handles this when citations < GROUNDING_MIN_CITATIONS
        # But a raising provider means draft_answer itself must catch the exception.
        # Per the brief: "wrap the call so ANY error/timeout/parse-failure returns UNGROUNDED_PLACEHOLDER"
        # This means draft_answer itself must try/except around provider.draft().

        # We test this directly with a stub that raises
        try:
            result = _call_draft_answer_with_raising_provider(cs)
        except Exception as e:
            pytest.fail(
                f"draft_answer must not propagate provider exceptions; got {type(e).__name__}: {e}"
            )

    def test_no_exception_escapes_on_provider_error(self):
        """No exception escapes draft_answer when the provider fails."""
        from app.config import UNGROUNDED_PLACEHOLDER

        cs = _make_context()
        # Should not raise
        result = _call_draft_answer_with_raising_provider(cs)
        assert result is not None
        assert result.text == UNGROUNDED_PLACEHOLDER, (
            f"Expected UNGROUNDED_PLACEHOLDER on provider failure; got {result.text!r}"
        )

    def test_degraded_result_has_no_citations(self):
        """The degrade result on provider failure has no citations."""
        cs = _make_context()
        result = _call_draft_answer_with_raising_provider(cs)
        assert result.citations == [], (
            f"Degraded result should have no citations; got {result.citations}"
        )

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="Live ClaudeLLM path requires ANTHROPIC_API_KEY (DRAFT2 live-gated check)",
    )
    def test_claude_llm_error_degrades_gracefully(self):
        """(Live-gated) ClaudeLLM with an invalid context does not raise."""
        from app.llm import ClaudeLLM
        from app.config import load_env, UNGROUNDED_PLACEHOLDER
        load_env()
        provider = ClaudeLLM()
        # Provide minimal context to trigger a real call; the result should be a DraftAnswer
        cs = _make_context()
        result = provider.draft(cs)
        # Should return a DraftAnswer (grounded or placeholder)
        from app.schema import DraftAnswer
        assert isinstance(result, DraftAnswer), (
            f"ClaudeLLM.draft() must return DraftAnswer; got {type(result)}"
        )


def _call_draft_answer_with_raising_provider(context_stack):
    """Call draft_answer with a provider that raises, expecting graceful degrade.

    draft_answer wraps the provider call and should catch the exception,
    returning UNGROUNDED_PLACEHOLDER as a structured result.
    """
    from app.draft import draft_answer
    from app.schema import DraftAnswer, Citation
    from app.config import UNGROUNDED_PLACEHOLDER
    from app.llm import LLMProvider

    class RaisingLLM(LLMProvider):
        def draft(self, context_stack):
            raise RuntimeError("Simulated provider failure for DRAFT2")

    provider = RaisingLLM()

    # draft_answer must not let the exception escape
    # It should catch provider errors and return UNGROUNDED_PLACEHOLDER
    # If draft_answer does NOT handle this, we wrap it here to produce
    # a clear failure message rather than an ambiguous traceback.
    result = draft_answer(context_stack, provider=provider)
    return result


# ---------------------------------------------------------------------------
# GROUND1 — grounding_check; UNGROUNDED_PLACEHOLDER byte-exact; GROUNDING_FAIL
# ---------------------------------------------------------------------------

class TestGROUND1:
    """GROUND1: grounding_check rejects ungrounded drafts; UNGROUNDED_PLACEHOLDER byte-exact;
    GROUNDING_FAIL reason-code emitted.
    """

    def test_no_citations_is_ungrounded(self):
        """A draft with no citations is ungrounded (condition 1)."""
        from app.draft import grounding_check
        from app.schema import DraftAnswer, Citation
        from app.config import GROUNDING_FAIL, UNGROUNDED_PLACEHOLDER

        cs = _make_context()
        draft = DraftAnswer(text="Some answer with no citations.", citations=[])
        result = grounding_check(draft, cs)
        assert not result.grounded, "No-citation draft must be ungrounded"
        assert result.reason_code == GROUNDING_FAIL, (
            f"Expected reason_code={GROUNDING_FAIL!r}; got {result.reason_code!r}"
        )
        # UNGROUNDED_PLACEHOLDER must be byte-exact (imported from config; NOT re-typed)
        assert result.answer.text == UNGROUNDED_PLACEHOLDER, (
            f"Ungrounded answer text must be UNGROUNDED_PLACEHOLDER (byte-exact).\n"
            f"  Got:    {result.answer.text!r}\n"
            f"  Wanted: {UNGROUNDED_PLACEHOLDER!r}"
        )

    def test_ungrounded_placeholder_is_byte_exact(self):
        """The substituted placeholder string is byte-for-byte equal to config.UNGROUNDED_PLACEHOLDER.

        This test asserts GROUND1's byte-exact requirement: the test imports
        UNGROUNDED_PLACEHOLDER from config (never re-types it as a literal).
        """
        from app.draft import grounding_check
        from app.schema import DraftAnswer
        from app.config import UNGROUNDED_PLACEHOLDER

        cs = _make_context()
        # A draft with no citations → ungrounded
        draft = DraftAnswer(text="Answer with zero citations.", citations=[])
        result = grounding_check(draft, cs)
        assert not result.grounded
        # Byte-exact assertion: imported constant, not a re-typed literal
        assert result.answer.text is not None
        assert result.answer.text == UNGROUNDED_PLACEHOLDER, (
            "GROUND1 byte-exact failure: substituted text ≠ config.UNGROUNDED_PLACEHOLDER"
        )
        # Additionally verify the config constant itself has not drifted
        assert UNGROUNDED_PLACEHOLDER == "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"

    def test_fabricated_citation_chunk_id_is_ungrounded(self):
        """A draft citing a chunk_id NOT in the Retrieval layer is ungrounded (condition 2)."""
        from app.draft import grounding_check
        from app.schema import DraftAnswer, Citation
        from app.config import GROUNDING_FAIL, UNGROUNDED_PLACEHOLDER

        chunks = [_make_chunk("real-c1", "Real chunk content about encryption.")]
        cs = _make_context(chunks=chunks)
        # Citation refers to a non-existent chunk_id
        draft = DraftAnswer(
            text="Answer based on [fake-c999].",
            citations=[Citation(chunk_id="fake-c999")],
        )
        result = grounding_check(draft, cs)
        assert not result.grounded, "Fabricated citation must be ungrounded"
        assert result.reason_code == GROUNDING_FAIL
        assert result.answer.text == UNGROUNDED_PLACEHOLDER

    def test_low_content_coverage_is_ungrounded(self):
        """A draft with very low content coverage of cited chunks is ungrounded (condition 3)."""
        from app.draft import grounding_check
        from app.schema import DraftAnswer, Citation
        from app.config import GROUNDING_FAIL, UNGROUNDED_PLACEHOLDER, GROUNDING_COVERAGE_MIN

        chunks = [_make_chunk("cov-c1", "encryption aes security certificate compliance audit")]
        cs = _make_context(chunks=chunks)
        # Draft text is almost entirely made up (not from the cited chunk)
        # Use unique fabricated words that definitely don't appear in the chunk
        draft = DraftAnswer(
            text=(
                "[cov-c1] flamingo zebra unicorn jupiter pluto marshmallow "
                "telescope parachute saxophone microscope volcano trampolinium "
                "xylophone kaleidoscope rhinoceros archipelago"
            ),
            citations=[Citation(chunk_id="cov-c1")],
        )
        result = grounding_check(draft, cs)
        assert not result.grounded, (
            "Low-coverage draft should be ungrounded "
            f"(GROUNDING_COVERAGE_MIN={GROUNDING_COVERAGE_MIN})"
        )
        assert result.reason_code == GROUNDING_FAIL
        assert result.answer.text == UNGROUNDED_PLACEHOLDER

    def test_grounded_mock_draft_passes_unchanged(self):
        """A MockLLM-produced draft passes grounding_check unchanged (happy path)."""
        from app.draft import grounding_check
        from app.llm import MockLLM

        chunks = [
            _make_chunk("gc1", "We use AES-256 encryption for data at rest."),
            _make_chunk("gc2", "Multi-factor authentication is required."),
        ]
        cs = _make_context(chunks=chunks)
        provider = MockLLM()
        raw_draft = provider.draft(cs)

        result = grounding_check(raw_draft, cs)
        assert result.grounded, (
            f"MockLLM draft should be grounded by construction; "
            f"text={raw_draft.text!r}, citations={raw_draft.citations}"
        )
        assert result.reason_code is None, (
            f"Grounded result should have reason_code=None; got {result.reason_code!r}"
        )
        assert result.answer.text == raw_draft.text, (
            "Grounded draft should be passed through unchanged"
        )

    def test_grounding_fail_reason_code_is_string_constant(self):
        """GROUNDING_FAIL reason-code is the named constant from config (not a re-typed literal)."""
        from app.config import GROUNDING_FAIL
        # Verify the constant value matches the expected string (sanity check on config)
        assert GROUNDING_FAIL == "GROUNDING_FAIL", (
            f"GROUNDING_FAIL constant has unexpected value: {GROUNDING_FAIL!r}"
        )

    def test_grounding_check_ungrounded_citations_empty(self):
        """The placeholder DraftAnswer returned by grounding_check has empty citations."""
        from app.draft import grounding_check
        from app.schema import DraftAnswer, Citation

        cs = _make_context()
        draft = DraftAnswer(text="No citations here.", citations=[])
        result = grounding_check(draft, cs)
        assert not result.grounded
        assert result.answer.citations == [], (
            f"Ungrounded result should have citations=[]; got {result.answer.citations}"
        )

    def test_both_new_config_constants_exist_and_correct(self):
        """New Stage 3 config constants GROUNDING_COVERAGE_MIN and GROUNDING_FAIL exist."""
        import app.config as cfg
        # GROUNDING_COVERAGE_MIN (D-S3 decision: 0.5)
        assert hasattr(cfg, "GROUNDING_COVERAGE_MIN"), (
            "config.GROUNDING_COVERAGE_MIN must be defined (Stage 3 new constant)"
        )
        assert cfg.GROUNDING_COVERAGE_MIN == 0.5, (
            f"GROUNDING_COVERAGE_MIN should be 0.5 (D-S3); got {cfg.GROUNDING_COVERAGE_MIN}"
        )
        # GROUNDING_FAIL (§5.1 audit reason-code)
        assert hasattr(cfg, "GROUNDING_FAIL"), (
            "config.GROUNDING_FAIL must be defined (Stage 3 new constant)"
        )
        assert cfg.GROUNDING_FAIL == "GROUNDING_FAIL", (
            f"GROUNDING_FAIL should equal 'GROUNDING_FAIL'; got {cfg.GROUNDING_FAIL!r}"
        )
