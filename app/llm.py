"""
app/llm.py — LLM adapter: LLMProvider interface + MockLLM (offline) + ClaudeLLM (live, gated).

Responsibility: define the LLMProvider ABC and the two concrete implementations.
  MockLLM   — offline, deterministic, seeded; the graded path for all tests and make demo.
  ClaudeLLM — lazy, network-gated live lane; used ONLY in make demo-live.

The LLMProvider interface is a graded contract: draft(context_stack) -> DraftAnswer.
Do NOT change the interface signature without surfacing as DECISION-NEEDED.

Enforces:
  DRAFT1 — MockLLM is deterministic offline; prompt built only from the ContextStack.
  DRAFT2 — Any error/timeout/parse-failure in draft() degrades to UNGROUNDED_PLACEHOLDER,
            never an unhandled exception, never a partial/invented answer.

Import-safe: no side effects at import — no network, no .env read, no Claude client built,
no data/* read. ClaudeLLM uses config._get_claude() (lazy singleton); MockLLM has no I/O.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from app.config import (
    DRAFT_MODEL,
    DRAFT_TEMPERATURE,
    MAX_OUTPUT_TOKENS,
    UNGROUNDED_PLACEHOLDER,
)
from app.schema import Citation, ContextStack, DraftAnswer


# ---------------------------------------------------------------------------
# LLMProvider — the graded interface (do NOT change; surface as DECISION-NEEDED)
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base class for LLM adapters.

    The single method `draft` is the only way code reaches a language model in this system.
    MockLLM (offline) and ClaudeLLM (gated live) both implement this interface; the vendor
    is a swap behind it.
    """

    @abstractmethod
    def draft(self, context_stack: ContextStack) -> DraftAnswer:
        """Draft an answer from the assembled context stack.

        Parameters
        ----------
        context_stack:
            The 4-layer context assembled by app/context_stack.py.

        Returns
        -------
        DraftAnswer
            A structured answer with text + citations. On any error, implementations
            MUST return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[]) —
            never raise, never return a partial/invented answer (DRAFT2).
        """
        ...


# ---------------------------------------------------------------------------
# Helpers shared by both implementations
# ---------------------------------------------------------------------------

# Regex to parse "[chunk_id]" markers out of a text string.
# Matches "[" + one or more non-]  characters + "]"
_CHUNK_ID_RE = re.compile(r"\[([^\]]+)\]")


def _parse_citations(text: str, retrieval_layer: list[str]) -> list[Citation]:
    """Extract [chunk_id] markers from `text` and return Citation objects.

    Only chunk_ids that appear in the retrieval_layer are considered valid.
    Unknown ids are silently dropped (grounding_check will catch fabricated citations).
    """
    # Build a set of known chunk_ids from the retrieval layer entries
    known_ids: set[str] = set()
    for entry in retrieval_layer:
        m = _CHUNK_ID_RE.match(entry)
        if m:
            known_ids.add(m.group(1))

    seen: set[str] = set()
    citations: list[Citation] = []
    for m in _CHUNK_ID_RE.finditer(text):
        cid = m.group(1)
        if cid in known_ids and cid not in seen:
            citations.append(Citation(chunk_id=cid))
            seen.add(cid)
    return citations


# ---------------------------------------------------------------------------
# MockLLM — offline, deterministic (graded path for tests + make demo)
# ---------------------------------------------------------------------------

class MockLLM(LLMProvider):
    """Deterministic offline LLM stub.

    Produces a DraftAnswer from the ContextStack without any network call.
    The output is fully deterministic: same ContextStack → identical DraftAnswer.

    Strategy: synthesize a short answer by joining the retrieval-layer entries
    (which are already "[chunk_id] text" strings) and citing all chunk_ids found.
    This ensures the mock draft is always grounded by construction and deterministic.
    """

    def draft(self, context_stack: ContextStack) -> DraftAnswer:
        """Return a deterministic DraftAnswer synthesized from the Retrieval layer."""
        retrieval = context_stack.retrieval
        if not retrieval:
            # No retrieval evidence — return placeholder (degrade path)
            return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])

        # Build a simple, deterministic answer from the retrieval entries.
        # Each entry is "[chunk_id] <text>"; we join them with a separator.
        # The text is deterministic because the retrieval list order is deterministic (RET3).
        parts: list[str] = []
        cited_ids: list[str] = []

        for entry in retrieval:
            m = _CHUNK_ID_RE.match(entry)
            if m:
                cid = m.group(1)
                # Strip the "[chunk_id] " prefix to get the chunk text
                chunk_text = entry[m.end():].strip()
                parts.append(f"Based on [{cid}]: {chunk_text}")
                cited_ids.append(cid)

        if not parts:
            return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])

        text = " ".join(parts)
        citations = [Citation(chunk_id=cid) for cid in cited_ids]
        return DraftAnswer(text=text, citations=citations)


# ---------------------------------------------------------------------------
# ClaudeLLM — lazy, network-gated live lane (used ONLY in make demo-live)
# ---------------------------------------------------------------------------

class ClaudeLLM(LLMProvider):
    """Claude API adapter (live lane only).

    Lazy: the Anthropic client is fetched via config._get_claude() on first call,
    never at import time. Import-safe: no client is built when this class is defined.

    DRAFT2 / RULE_SAFE_TERMINAL: any error — API error, timeout, parse failure,
    missing ANTHROPIC_API_KEY — degrades to DraftAnswer(text=UNGROUNDED_PLACEHOLDER,
    citations=[]) and is never re-raised. The pipeline/audit layer treats this as an
    ungrounded result and routes for human review.
    """

    def _build_prompt(self, context_stack: ContextStack) -> str:
        """Build the prompt string from the 4 layers of the context stack.

        The 4-layer order is: Instruction → Retrieval → Constraint → State.
        Everything the model sees comes from the ContextStack; nothing else.
        """
        retrieval_block = "\n".join(
            f"  {entry}" for entry in context_stack.retrieval
        ) or "  (no retrieved evidence)"

        return (
            f"=== INSTRUCTIONS ===\n{context_stack.instruction}\n\n"
            f"=== RETRIEVAL CONTEXT ===\n{retrieval_block}\n\n"
            f"=== CONSTRAINTS ===\n{context_stack.constraint}\n\n"
            f"=== STATE ===\n{context_stack.state}\n\n"
            "=== TASK ===\n"
            "Draft a grounded answer to the questionnaire item above. "
            "Cite every chunk you draw from using its [chunk_id] marker exactly as shown "
            "in the Retrieval Context. "
            "If the retrieved evidence is insufficient, say so clearly rather than speculating. "
            "Return your answer as plain text."
        )

    def draft(self, context_stack: ContextStack) -> DraftAnswer:
        """Call the Claude API and return a DraftAnswer.

        On ANY failure (API error, timeout, parse error, missing key, etc.) returns
        DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[]) — never raises (DRAFT2).
        """
        try:
            # Lazy client construction — _get_claude() raises if key is absent
            from app.config import _get_claude  # noqa: PLC0415 — deferred intentionally
            client = _get_claude()

            prompt = self._build_prompt(context_stack)

            response = client.messages.create(
                model=DRAFT_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=DRAFT_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text content from the response
            raw_text: str = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw_text += block.text

            raw_text = raw_text.strip()
            if not raw_text:
                return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])

            # Parse citations from the response text
            citations = _parse_citations(raw_text, context_stack.retrieval)

            return DraftAnswer(text=raw_text, citations=citations)

        except Exception:
            # DRAFT2: any error (API error, timeout, parse failure, missing key) degrades
            # to UNGROUNDED_PLACEHOLDER — never re-raised, never a partial/invented answer.
            return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])
