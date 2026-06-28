"""
tests/test_sources_trailer.py — Plan A: the Sources-trailer citation recovery.

ADD-only. The draft TASK now asks the model to end its answer with a "Sources: [kb-001], ..."
line. _parse_citations already scans the WHOLE answer for [chunk_id] markers, so the trailer's
ids are captured even when the model drops the per-sentence inline markers (the cit=0 failure
mode). These tests pin that recovery behavior and that the live draft prompt carries the rule.
"""

from __future__ import annotations

from app.llm import ClaudeLLM, _parse_citations
from app.schema import ContextStack


_RETRIEVAL = ["[kb-001] data encrypted at rest using AES-256", "[kb-008] access is logged via PAM"]


def test_sources_trailer_recovers_citations_without_inline_markers():
    """An answer with NO inline markers but a trailing Sources: line still parses its citations."""
    draft = "All customer data is encrypted at rest and every access is logged.\nSources: [kb-001], [kb-008]"
    cites = _parse_citations(draft, _RETRIEVAL)
    assert {c.chunk_id for c in cites} == {"kb-001", "kb-008"}


def test_sources_trailer_still_drops_unknown_ids():
    """A Sources line citing a chunk that was NOT retrieved is dropped (no fabrication)."""
    draft = "Some answer.\nSources: [kb-001], [kb-999]"
    cites = _parse_citations(draft, _RETRIEVAL)
    assert {c.chunk_id for c in cites} == {"kb-001"}  # kb-999 not in retrieval → dropped


def test_draft_prompt_requires_sources_line():
    """The live draft TASK asks for the Sources: trailer (and keeps the pinned guarantees)."""
    stack = ContextStack(
        instruction="i", question="Do you encrypt at rest?",
        retrieval=_RETRIEVAL, constraint="c", state="s",
    )
    prompt = ClaudeLLM()._build_prompt(stack)
    assert "Sources:" in prompt
    # pinned guarantees still hold
    assert "<thinking>" not in prompt
    assert "[chunk_id]" in prompt
    assert "ONLY the answer" in prompt
