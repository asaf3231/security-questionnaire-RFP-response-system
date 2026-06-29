"""
tests/test_submit_answer_tool.py — the submit_answer structured tool-output path.

ADD-only. Covers ClaudeLLM.draft when the live model returns a forced `submit_answer`
tool call (citations as a schema-required field, not scraped from prose):
  - answer + citations extracted into the DraftAnswer;
  - citations not in the retrieval layer are dropped (no fabrication);
  - inline [chunk_id] markers in the answer are ALSO recovered (union);
  - empty / malformed tool input degrades to UNGROUNDED_PLACEHOLDER (DRAFT2);
  - a text-only response still flows through the prose fallback (backward compat).

Only the external boundary (the Anthropic client) is faked — the real _build_prompt /
_extract_tool_answer / _known_chunk_ids / draft internals run.
"""

from __future__ import annotations

from app.config import UNGROUNDED_PLACEHOLDER
from app.llm import ClaudeLLM
from app.schema import ContextStack

_RETRIEVAL = [
    "[kb-001] all customer data is encrypted at rest using AES-256",
    "[kb-008] employee access is logged and reviewed via PAM",
]


def _stack() -> ContextStack:
    return ContextStack(
        instruction="Answer the question using only the retrieval context.",
        question="Do you encrypt data at rest?",
        retrieval=_RETRIEVAL,
        constraint="Cite every fact.",
        state="item 1 of 1",
    )


# --- Behaviour-faithful fakes for the Anthropic client (external boundary only) ---

class _ToolUseBlock:
    def __init__(self, name: str, tool_input: dict) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = tool_input


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, blocks: list) -> None:
        self.content = blocks


class _Messages:
    def __init__(self, blocks: list) -> None:
        self._blocks = blocks

    def create(self, **kwargs):  # mirrors anthropic client.messages.create
        return _Response(self._blocks)


class _Client:
    def __init__(self, blocks: list) -> None:
        self.messages = _Messages(blocks)


def _patch(monkeypatch, blocks: list) -> None:
    monkeypatch.setattr("app.config._get_claude", lambda: _Client(blocks))


# --- Tests ---

def test_tool_answer_and_citations_extracted(monkeypatch):
    block = _ToolUseBlock("submit_answer", {
        "answer": "Yes, all customer data is encrypted at rest using AES-256.",
        "citations": ["kb-001", "kb-008"],
    })
    _patch(monkeypatch, [block])
    draft = ClaudeLLM().draft(_stack())
    assert draft.text == "Yes, all customer data is encrypted at rest using AES-256."
    assert {c.chunk_id for c in draft.citations} == {"kb-001", "kb-008"}


def test_unknown_citation_dropped(monkeypatch):
    block = _ToolUseBlock("submit_answer", {
        "answer": "Data is encrypted at rest.",
        "citations": ["kb-001", "kb-999"],  # kb-999 was never retrieved
    })
    _patch(monkeypatch, [block])
    draft = ClaudeLLM().draft(_stack())
    assert {c.chunk_id for c in draft.citations} == {"kb-001"}


def test_inline_markers_unioned_with_tool_citations(monkeypatch):
    block = _ToolUseBlock("submit_answer", {
        "answer": "Data is encrypted [kb-001]. Access is logged [kb-008].",
        "citations": ["kb-001"],  # tool lists only one; inline mentions both
    })
    _patch(monkeypatch, [block])
    draft = ClaudeLLM().draft(_stack())
    assert {c.chunk_id for c in draft.citations} == {"kb-001", "kb-008"}


def test_empty_answer_degrades_to_placeholder(monkeypatch):
    block = _ToolUseBlock("submit_answer", {"answer": "   ", "citations": ["kb-001"]})
    _patch(monkeypatch, [block])
    draft = ClaudeLLM().draft(_stack())
    assert draft.text == UNGROUNDED_PLACEHOLDER
    assert draft.citations == []


def test_malformed_tool_input_degrades_to_placeholder(monkeypatch):
    # No "answer" key → _extract_tool_answer returns (None, ...) → prose fallback →
    # no text block present → UNGROUNDED_PLACEHOLDER (DRAFT2).
    block = _ToolUseBlock("submit_answer", {"citations": ["kb-001"]})
    _patch(monkeypatch, [block])
    draft = ClaudeLLM().draft(_stack())
    assert draft.text == UNGROUNDED_PLACEHOLDER
    assert draft.citations == []


def test_text_only_response_uses_prose_fallback(monkeypatch):
    # No tool_use block (API didn't honor the tool / a stub) → existing prose path runs.
    _patch(monkeypatch, [_TextBlock("Data is encrypted at rest [kb-001].")])
    draft = ClaudeLLM().draft(_stack())
    assert draft.text == "Data is encrypted at rest [kb-001]."
    assert {c.chunk_id for c in draft.citations} == {"kb-001"}
