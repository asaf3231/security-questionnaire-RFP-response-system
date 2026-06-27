"""
app/draft.py — draft_answer() + grounding gate (RULE_GROUNDED_ONLY chokepoint).

Responsibility: call the LLMProvider to draft an answer from the context stack,
then pass the result through grounding_check() which enforces RULE_GROUNDED_ONLY.
The grounding gate is the core safety boundary: ungrounded answers are replaced
with UNGROUNDED_PLACEHOLDER byte-for-byte and never asserted as answers.

RULE_GROUNDED_ONLY enforced here (app/draft.py grounding_check) — this is the
single chokepoint; the audit reason-code GROUNDING_FAIL is emitted here.

Enforces:
  GROUND1   — grounding_check rejects ungrounded drafts; substitutes UNGROUNDED_PLACEHOLDER
              (byte-exact from config); emits GROUNDING_FAIL reason-code.
  DRAFT1    — draft_answer(context_stack) returns DraftAnswer; offline MockLLM used by default.
  DRAFT2    — any provider error degrades to UNGROUNDED_PLACEHOLDER (handled in llm.py;
              the degrade result also passes grounding_check as "ungrounded → placeholder").
  LEAK-G    — no asserted answer without a cited retrieved chunk (same as GROUND1).

Import-safe: no side effects at import — no network, no .env, no data/* read, no file written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import (
    GROUNDING_COVERAGE_MIN,
    GROUNDING_FAIL,
    GROUNDING_MIN_CITATIONS,
    RULE_GROUNDED_ONLY,
    UNGROUNDED_PLACEHOLDER,
)
from app.schema import Citation, ContextStack, DraftAnswer
from app.llm import LLMProvider, MockLLM

# ---------------------------------------------------------------------------
# Stopword set — named constant (no magic values inline; CLAUDE.md §8)
# Used by coverage check: exclude these from "significant content tokens" so
# common function words don't inflate the coverage score.
# ---------------------------------------------------------------------------

_COVERAGE_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "be", "as", "are",
    "was", "were", "been", "that", "this", "these", "those", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "not", "no", "nor", "so", "yet", "both", "either", "each",
    "more", "most", "other", "such", "than", "then", "when", "where",
    "which", "who", "whom", "how", "what", "any", "all", "our", "we",
    "their", "they", "us", "if", "can", "into", "about", "up", "also",
})

# Tokenizer re-used from retrieval for consistency (deterministic, no locale)
_TOKEN_RE = re.compile(r"[^a-z0-9]+")

# Regex for extracting "[chunk_id]" markers from text
_CHUNK_ID_RE = re.compile(r"\[([^\]]+)\]")


# ---------------------------------------------------------------------------
# GroundingResult — small dataclass returned by grounding_check()
# ---------------------------------------------------------------------------

@dataclass
class GroundingResult:
    """Result of grounding_check(): whether the draft is grounded and the final answer.

    Attributes
    ----------
    grounded:
        True  → draft is grounded; answer is unchanged.
        False → draft failed grounding; answer has been replaced with UNGROUNDED_PLACEHOLDER.
    answer:
        The DraftAnswer to use (either the original or the placeholder-substituted one).
    reason_code:
        GROUNDING_FAIL when grounded=False; None when grounded=True.
        This is the §5.1 audit reason-code (imported from config.GROUNDING_FAIL).
    """
    grounded: bool
    answer: DraftAnswer
    reason_code: str | None = field(default=None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _significant_tokens(text: str) -> set[str]:
    """Return lowercase alphanumeric tokens from text, minus stopwords."""
    raw = [tok for tok in _TOKEN_RE.split(text.lower()) if tok]
    return {tok for tok in raw if tok not in _COVERAGE_STOPWORDS}


def _retrieval_chunk_ids(context_stack: ContextStack) -> set[str]:
    """Extract the set of chunk_ids present in the Retrieval layer."""
    ids: set[str] = set()
    for entry in context_stack.retrieval:
        m = _CHUNK_ID_RE.match(entry)
        if m:
            ids.add(m.group(1))
    return ids


def _cited_chunks_text(citations: list[Citation], context_stack: ContextStack) -> str:
    """Return the concatenated text of the cited chunks from the Retrieval layer.

    Used for content-coverage checking (condition 3 of the grounding gate).
    """
    # Build a map from chunk_id → chunk text (strip the "[chunk_id] " prefix)
    chunk_texts: dict[str, str] = {}
    for entry in context_stack.retrieval:
        m = _CHUNK_ID_RE.match(entry)
        if m:
            cid = m.group(1)
            chunk_text = entry[m.end():].strip()
            chunk_texts[cid] = chunk_text

    cited_text_parts: list[str] = []
    for citation in citations:
        if citation.chunk_id in chunk_texts:
            cited_text_parts.append(chunk_texts[citation.chunk_id])
    return " ".join(cited_text_parts)


def _compute_coverage(draft_text: str, cited_text: str) -> float:
    """Compute the content-coverage fraction.

    Returns the fraction of significant tokens in draft_text that also appear
    in cited_text. If draft_text has no significant tokens, returns 1.0 (vacuously
    grounded — the answer has no assertable content to check).
    """
    draft_tokens = _significant_tokens(draft_text)
    if not draft_tokens:
        return 1.0
    cited_tokens = _significant_tokens(cited_text)
    overlap = draft_tokens.intersection(cited_tokens)
    return len(overlap) / len(draft_tokens)


def _ungrounded_result() -> GroundingResult:
    """Return a GroundingResult for an ungrounded draft (chokepoint for RULE_GROUNDED_ONLY)."""
    return GroundingResult(
        grounded=False,
        answer=DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[]),
        reason_code=GROUNDING_FAIL,  # §5.1 audit reason-code; imported from config
    )


# ---------------------------------------------------------------------------
# grounding_check() — the graded contract (do NOT change signature; surface as DECISION-NEEDED)
# ---------------------------------------------------------------------------

def grounding_check(
    draft: DraftAnswer,
    context_stack: ContextStack,
) -> GroundingResult:
    """Enforce RULE_GROUNDED_ONLY on a draft answer.

    A draft is **ungrounded** if ANY of the following holds:
      1. len(draft.citations) < GROUNDING_MIN_CITATIONS
         (insufficient number of cited chunks)
      2. any citation.chunk_id is NOT in the Retrieval layer's known chunk_ids
         (fabricated / unretrieved citation)
      3. content coverage < GROUNDING_COVERAGE_MIN
         (the significant content tokens of the draft_text are not well-supported
         by the union of the cited chunks' text)

    Ungrounded → UNGROUNDED_PLACEHOLDER (byte-exact from config; asserted in GROUND1 test)
                 + reason_code = GROUNDING_FAIL
    Grounded   → original draft, reason_code = None

    The UNGROUNDED_PLACEHOLDER is the byte-exact string from config.UNGROUNDED_PLACEHOLDER.
    Tests assert it byte-for-byte against config.UNGROUNDED_PLACEHOLDER (not a re-typed literal).
    """
    # --- Condition 1: insufficient citations ---
    if len(draft.citations) < GROUNDING_MIN_CITATIONS:
        return _ungrounded_result()

    # --- Condition 2: any cited chunk_id not in the Retrieval layer ---
    known_ids = _retrieval_chunk_ids(context_stack)
    for citation in draft.citations:
        if citation.chunk_id not in known_ids:
            return _ungrounded_result()

    # --- Condition 3: content coverage below threshold ---
    # If the draft text IS the placeholder itself (e.g. from a provider degrade),
    # allow it through as-is (it will fail condition 1 because citations=[] anyway,
    # but we guard here for defence-in-depth).
    if draft.text == UNGROUNDED_PLACEHOLDER:
        return _ungrounded_result()

    cited_text = _cited_chunks_text(draft.citations, context_stack)
    coverage = _compute_coverage(draft.text, cited_text)
    if coverage < GROUNDING_COVERAGE_MIN:
        return _ungrounded_result()

    # All conditions passed → grounded
    return GroundingResult(grounded=True, answer=draft, reason_code=None)


# ---------------------------------------------------------------------------
# draft_answer() — the graded contract (do NOT change signature; surface as DECISION-NEEDED)
# ---------------------------------------------------------------------------

def draft_answer(
    context_stack: ContextStack,
    *,
    provider: LLMProvider | None = None,
) -> DraftAnswer:
    """Draft a grounded answer for one questionnaire item.

    Steps:
      1. Resolve provider → default to MockLLM() (the offline, deterministic path).
      2. Call provider.draft(context_stack) to get a raw draft.
         Any provider error is handled inside the provider and returns UNGROUNDED_PLACEHOLDER.
      3. Pass the raw draft through grounding_check(); return grounding_check().answer.
         The reason_code (GROUNDING_FAIL or None) is returned as part of GroundingResult
         and consumed by the pipeline/audit layer in Stages 5–6.

    Parameters
    ----------
    context_stack:
        The assembled 4-layer context from app/context_stack.py.
    provider:
        An LLMProvider to use. Defaults to MockLLM() (offline/deterministic).
        Pass ClaudeLLM() only from the gated live lane (make demo-live).

    Returns
    -------
    DraftAnswer
        Either the grounded raw draft, or DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])
        if the grounding gate fired (RULE_GROUNDED_ONLY).
    """
    if provider is None:
        provider = MockLLM()

    try:
        raw = provider.draft(context_stack)
    except Exception:
        # DRAFT2 / RULE_SAFE_TERMINAL: any provider error (API error, timeout, parse failure,
        # missing key, unexpected exception) degrades to UNGROUNDED_PLACEHOLDER.
        # Never re-raised; never a partial/invented answer.
        return DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])

    result = grounding_check(raw, context_stack)
    return result.answer
