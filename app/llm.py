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

import os
import re
from abc import ABC, abstractmethod

from app.config import (
    DRAFT_MODEL,
    DRAFT_TEMPERATURE,
    MAX_OUTPUT_TOKENS,
    REFINE_MAX_TOKENS,
    UNGROUNDED_PLACEHOLDER,
)
from app.query_optimizer import strip_thinking_block
from app.schema import Citation, ContextStack, DraftAnswer


# ---------------------------------------------------------------------------
# Live-lane prompt scaffolds (Stage 10) — named constants, never inline prose.
# The <thinking> reasoning these request is ALWAYS stripped by code before any
# gate/export sees it (strip_thinking_block); it is a quality scaffold, NOT a
# governance mechanism — the RULE_* chokepoints stay code-enforced (CLAUDE.md §5).
# ---------------------------------------------------------------------------

# QUERY_REFINEMENT directive: reason in <thinking>, emit ONLY clean keywords after it.
_REFINE_DIRECTIVE: str = (
    "You optimize search queries for a security / compliance questionnaire knowledge base.\n"
    "Analyze the user question, expand it with synonyms and technical context related to our "
    "KB domain, and output only an optimized search query for our knowledge base.\n"
    "First, inside <thinking>...</thinking>, decompose the question, identify the security "
    "concepts, and expand them into technical synonyms for optimal BM25 retrieval.\n"
    "Then, AFTER the closing </thinking> tag, output ONLY the space-separated clean keywords — "
    "no prose, no punctuation, no explanation.\n"
    "Example:\n"
    "Question: How do you handle data encryption?\n"
    "<thinking>Concept: encryption at rest/transit. Synonyms: AES-256, TLS, SSL, KMS.</thinking> "
    "encryption AES TLS rest transit"
)
# Bounds for the live QUERY_REFINEMENT call live in app/config.py §9 (REFINE_MAX_TOKENS).

# NOTE (2026-06-28, two-key authorized spec change): the DRAFT prompt no longer injects a
# <thinking> reasoning scaffold. Live evidence (redteam/LIVE_RUN_FINDINGS.nothinking 40/50
# grounded vs .stage10 25/100 WITH the scaffold) showed it makes the model emit reasoning
# prose and drop inline [chunk_id] citations, tanking live grounding. The draft now requests
# inline citations + answer-only output (see ClaudeLLM._build_prompt). The DEFENSIVE strip in
# ClaudeLLM.draft (strip_thinking_block) remains — the model may still emit reasoning unasked.
# The refine-query <thinking> scaffold (_REFINE_DIRECTIVE above) is unaffected and retained.
#
# NOTE (2026-06-28, two-key authorized — Asaf go-ahead): the DRAFT TASK now adds (a) a mandatory
# CITATION FORMAT rule (every factual sentence MUST end with its [chunk_id]; zero markers ⇒
# INVALID) and (b) a one-shot worked example of the inline-citation format. Rationale: zero-shot
# instruction-only citing made the model intermittently drop [chunk_id] markers ⇒ cit=0 ⇒ the
# grounding gate rejected covered answers. Live evidence on case_bulk20 (18 covered + 2 genuine
# negatives): grounded 10/20 → 14/20; false-ungrounded on covered items 8 → 4. The 2 negatives
# (i19 bug-bounty, i20 BC/DR) stay correctly ungrounded. (Live lane has run-to-run variance.)


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

    def refine_query(self, question: str) -> str:
        """Refine a raw question into an optimized search query (Stage 10, QUERY_REFINEMENT).

        Concrete default = IDENTITY (return the question unchanged). This is deliberately
        NOT abstract: existing LLMProvider subclasses (and MockLLM) implement only draft(),
        and the identity default means the offline/graded path leaves the retrieval query
        byte-identical — RET2/RET3 and the deterministic suite are unaffected.

        Only ClaudeLLM (the live lane) overrides this with real query expansion. The caller
        app/query_optimizer.refine_query() strips any <thinking> reasoning and falls back to
        the original question on unusable output, so retrieval always gets a valid query.
        """
        return question


# ---------------------------------------------------------------------------
# Helpers shared by both implementations
# ---------------------------------------------------------------------------

# Regex to parse "[chunk_id]" markers out of a text string.
# Matches "[" + one or more non-]  characters + "]"
_CHUNK_ID_RE = re.compile(r"\[([^\]]+)\]")


def _known_chunk_ids(retrieval_layer: list[str]) -> set[str]:
    """Return the set of chunk_ids present in the retrieval layer entries.

    Each entry is a "[chunk_id] text" string; the leading [chunk_id] marker is the id.
    Used to validate citations (model-claimed or prose-parsed) against what was retrieved.
    """
    known_ids: set[str] = set()
    for entry in retrieval_layer:
        m = _CHUNK_ID_RE.match(entry)
        if m:
            known_ids.add(m.group(1))
    return known_ids


def _parse_citations(text: str, retrieval_layer: list[str]) -> list[Citation]:
    """Extract [chunk_id] markers from `text` and return Citation objects.

    Only chunk_ids that appear in the retrieval_layer are considered valid.
    Unknown ids are silently dropped (grounding_check will catch fabricated citations).
    """
    known_ids = _known_chunk_ids(retrieval_layer)

    seen: set[str] = set()
    citations: list[Citation] = []
    for m in _CHUNK_ID_RE.finditer(text):
        cid = m.group(1)
        if cid in known_ids and cid not in seen:
            citations.append(Citation(chunk_id=cid))
            seen.add(cid)
    return citations


# ---------------------------------------------------------------------------
# submit_answer tool — structured, schema-enforced citations (live lane only).
# Makes `citations` a REQUIRED field instead of regex-scraping [chunk_id] from prose,
# which the model intermittently drops (the cit=0 grounding failure). The tool is the
# primary channel; the prose path remains as a fallback (see ClaudeLLM.draft).
# ---------------------------------------------------------------------------
_SUBMIT_ANSWER_TOOL: dict = {
    "name": "submit_answer",
    "description": (
        "Submit the grounded answer to the security questionnaire item. Use ONLY the "
        "Retrieval Context. Every chunk_id you relied on MUST be listed in citations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The answer, drawn ONLY from the Retrieval Context.",
            },
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The chunk_ids supporting the answer — the bracketed ids shown at the "
                    "start of each Retrieval Context entry; at least one. Use only ids that "
                    "appear in the Retrieval Context."
                ),
            },
        },
        "required": ["answer", "citations"],
    },
}


def _extract_tool_answer(response) -> tuple[str | None, list[str]]:
    """Return (answer, citations) from a forced submit_answer tool call, or (None, []).

    Scans response.content for a tool_use block named submit_answer (the real anthropic
    SDK shape: block.type == "tool_use", block.name, block.input dict). Returns (None, [])
    when no such block exists — e.g. a text-only response (test fakes / API not honoring the
    tool) — so the caller falls back to the prose path. Faithful to the external boundary only.
    """
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_answer":
            data = getattr(block, "input", None) or {}
            answer = data.get("answer")
            citations = data.get("citations") or []
            if not isinstance(citations, list):
                citations = []
            citations = [c for c in citations if isinstance(c, str)]
            return (answer if isinstance(answer, str) else None), citations
    return None, []


def _maybe_show(title: str, body: str) -> None:
    """Print a Claude request prompt or response when COMET_SHOW_PROMPTS is set (REPL live lane).

    Off by default → make demo-live and the offline suite are unaffected. The body holds only
    synthetic KB content + the question / the model's answer (no secret/PII), so printing is safe.
    """
    if not os.environ.get("COMET_SHOW_PROMPTS"):
        return
    print(f"\n┌─ {title} ──────────────────────────────")
    for line in (body.splitlines() or [body]):
        print(f"│ {line}")
    print("└───────────────────────────────────────────────────")


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
        """Build the prompt string from the context stack.

        Order: Instruction → Question → Retrieval → Constraint → State → Task.
        Everything the model sees comes from the ContextStack; nothing else. The QUESTION
        block (Stage 10) carries the ORIGINAL questionnaire question so the model answers
        the actual question rather than reverse-engineering it from the retrieved chunks.
        The TASK requests a <thinking> block (stripped by code in draft()).
        """
        retrieval_block = "\n".join(
            f"  {entry}" for entry in context_stack.retrieval
        ) or "  (no retrieved evidence)"

        question_block = ""
        if context_stack.question:
            question_block = f"=== QUESTION ===\n{context_stack.question}\n\n"

        return (
            f"=== INSTRUCTIONS ===\n{context_stack.instruction}\n\n"
            f"{question_block}"
            f"=== RETRIEVAL CONTEXT ===\n{retrieval_block}\n\n"
            f"=== CONSTRAINTS ===\n{context_stack.constraint}\n\n"
            f"=== STATE ===\n{context_stack.state}\n\n"
            "=== TASK ===\n"
            "Draft a grounded answer to the QUESTION above using ONLY the Retrieval Context.\n"
            "\n"
            "CITATION FORMAT (mandatory):\n"
            "1. Cite inline: every sentence that states a fact ends with the [chunk_id] it is drawn from.\n"
            "2. ALWAYS end your answer with a final line listing every chunk you used, e.g.\n"
            "     Sources: [kb-001], [kb-008]\n"
            "An answer containing zero [chunk_id] markers is INVALID and will be rejected.\n"
            "Example of the required format (illustration only — do not reuse this content):\n"
            "  Yes, data is encrypted at rest using AES-256 [kb-001]. Keys are rotated quarterly "
            "[kb-001], and all access is logged [kb-008].\n"
            "  Sources: [kb-001], [kb-008]\n"
            "\n"
            "If the Retrieval Context does not address the QUESTION, say so plainly and do NOT "
            "invent a [chunk_id] or a Sources line. Return ONLY the answer — no preamble, no reasoning section."
        )

    def refine_query(self, question: str) -> str:
        """Live QUERY_REFINEMENT (Stage 10): expand the question into an optimized search query.

        Calls Claude with _REFINE_DIRECTIVE (reason in <thinking>, emit clean keywords after).
        Returns the RAW model text; app/query_optimizer.refine_query() strips <thinking> and
        validates. On ANY error/empty output, degrades to the original question (never raises).
        """
        try:
            from app.config import _get_claude  # noqa: PLC0415 — deferred intentionally
            client = _get_claude()

            prompt = f"{_REFINE_DIRECTIVE}\n\nQuestion: {question}"
            _maybe_show("→ Claude request 1 · refine_query (prompt)", prompt)
            response = client.messages.create(
                model=DRAFT_MODEL,
                max_tokens=REFINE_MAX_TOKENS,
                temperature=DRAFT_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text: str = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw_text += block.text

            raw_text = raw_text.strip()
            _maybe_show("← Claude request 1 · refine_query (response)", raw_text)
            return raw_text if raw_text else question

        except Exception:
            # Refinement is best-effort; degrade to the original question (RULE_SAFE_TERMINAL spirit).
            return question

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
            _maybe_show("→ Claude request 2 · draft (prompt)", prompt)

            response = client.messages.create(
                model=DRAFT_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=DRAFT_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
                tools=[_SUBMIT_ANSWER_TOOL],
                tool_choice={"type": "tool", "name": "submit_answer"},
            )

            # Primary path: the model returned a structured submit_answer tool call, so
            # `citations` is a schema-required field (not scraped from prose). This removes the
            # intermittent cit=0 failure where the model drops inline [chunk_id] markers.
            tool_answer, tool_citations = _extract_tool_answer(response)
            if tool_answer is not None:
                clean_tool = strip_thinking_block(tool_answer).strip()
                _maybe_show("← Claude request 2 · draft (submit_answer)", clean_tool)
                if not clean_tool:
                    return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])
                known = _known_chunk_ids(context_stack.retrieval)
                seen: set[str] = set()
                citations: list[Citation] = []
                # Validated tool citations first (drop unknown/fabricated, dedup), then recover
                # any inline [chunk_id] markers the model also wrote into the answer text.
                for cid in tool_citations:
                    if cid in known and cid not in seen:
                        citations.append(Citation(chunk_id=cid))
                        seen.add(cid)
                for c in _parse_citations(clean_tool, context_stack.retrieval):
                    if c.chunk_id not in seen:
                        citations.append(c)
                        seen.add(c.chunk_id)
                return DraftAnswer(text=clean_tool, citations=citations)

            # Fallback path: no tool_use block (test fakes / API didn't honor the tool) — parse
            # the prose response exactly as before.
            raw_text: str = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw_text += block.text

            raw_text = raw_text.strip()
            _maybe_show("← Claude request 2 · draft (response)", raw_text)
            if not raw_text:
                return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])

            # Stage 10: strip the <thinking> reasoning BEFORE parsing citations and BEFORE
            # building the DraftAnswer, so grounding_check + export only ever see the clean,
            # citation-bearing answer (an un-stripped reasoning block would dilute coverage
            # and leak reasoning into the exported document).
            clean_text = strip_thinking_block(raw_text)
            if not clean_text:
                return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])

            # Parse citations from the cleaned response text
            citations = _parse_citations(clean_text, context_stack.retrieval)

            return DraftAnswer(text=clean_text, citations=citations)

        except Exception:
            # DRAFT2: any error (API error, timeout, parse failure, missing key) degrades
            # to UNGROUNDED_PLACEHOLDER — never re-raised, never a partial/invented answer.
            return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])
