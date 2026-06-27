"""
app/query_optimizer.py — Intelligent Query Refinement stage (Stage 10).

Responsibility: turn a raw questionnaire question into an optimized BM25 search query
via the LLM, then deterministically strip any <thinking> reasoning the model emitted so
ONLY clean keywords reach retrieval. This is the QUERY_REFINEMENT stage that runs BEFORE
app/retrieval.py.

Design (CLAUDE.md §5/§8 — "code restrains the model, not prompts"):
  - The LLM may reason inside <thinking>...</thinking>; the deterministic regex util
    strip_thinking_block() removes that block so the model's reasoning is NEVER trusted
    as output and never reaches BM25.
  - All model access goes through the LLMProvider interface (app/llm.py) — the only way
    out to a model in this system. The offline/graded path (MockLLM) inherits the
    identity default (refine_query(q) == q), so deterministic retrieval is unchanged.
  - RULE_SAFE_TERMINAL spirit: ANY failure (provider error, empty/garbage output) degrades
    to the ORIGINAL question — never a crash, never an empty query.

Import-safe: no side effects at import — no network, no .env, no data/* read, no file written.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle with app/llm.py (which imports this util)
    from app.llm import LLMProvider


# ---------------------------------------------------------------------------
# Deterministic <thinking> strip harness (named patterns — no magic literals inline)
# ---------------------------------------------------------------------------

# Well-formed block: <thinking> ... </thinking> (multiline, case-insensitive). The close
# tag is matched tolerantly (`</thinking[^>]*>`) so a malformed close like `</thinking foo>`
# still closes the block — otherwise the open-to-end fallback would delete the real answer.
_THINKING_BLOCK_RE = re.compile(r"<thinking\b[^>]*>.*?</thinking\b[^>]*>", re.DOTALL | re.IGNORECASE)
# Dangling open tag with NO close at all: strip from the open tag to end of text (tolerant).
_THINKING_OPEN_TO_END_RE = re.compile(r"<thinking\b[^>]*>.*$", re.DOTALL | re.IGNORECASE)
# Any stray opening/closing thinking tag left over (with or without attributes).
_STRAY_THINKING_TAG_RE = re.compile(r"</?thinking\b[^>]*>", re.IGNORECASE)

# Upper bound on a refined query so a runaway model response cannot blow up retrieval.
_MAX_REFINED_QUERY_CHARS = 512


def strip_thinking_block(text: str) -> str:
    """Remove <thinking>...</thinking> reasoning from `text`, returning the clean remainder.

    Deterministic and total: handles well-formed blocks, a dangling unclosed <thinking>
    (everything from the open tag to end is dropped → safe), and any stray tags. Returns
    the stripped remainder; an empty string if nothing usable remains (callers fall back).
    """
    if not text:
        return ""
    cleaned = _THINKING_BLOCK_RE.sub(" ", text)
    cleaned = _THINKING_OPEN_TO_END_RE.sub(" ", cleaned)
    cleaned = _STRAY_THINKING_TAG_RE.sub(" ", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# refine_query() — the QUERY_REFINEMENT stage entry point
# ---------------------------------------------------------------------------

def refine_query(question: str, *, provider: "LLMProvider") -> str:
    """Return an optimized BM25 search query for `question` via the provider.

    Steps:
      1. Call provider.refine_query(question). MockLLM (offline) returns the question
         unchanged (identity default); ClaudeLLM (live) expands it with synonyms/technical
         terms inside <thinking> and emits keywords after the block.
      2. strip_thinking_block() removes any reasoning so only clean keywords remain.
      3. Validate: non-empty, contains ≥1 alphanumeric token, bounded length.
      4. On ANY failure or unusable output, degrade to the ORIGINAL question
         (RULE_SAFE_TERMINAL spirit) — retrieval always receives a valid query.

    Parameters
    ----------
    question:
        The raw questionnaire item question.
    provider:
        An LLMProvider. The pipeline passes the same provider used for drafting.

    Returns
    -------
    str
        The optimized query, or the original question if refinement produced nothing usable.
    """
    if not question or not question.strip():
        return question

    try:
        raw = provider.refine_query(question)
    except Exception:
        # RULE_SAFE_TERMINAL spirit: refinement is best-effort; never crash the pipeline.
        return question

    if not isinstance(raw, str):
        return question

    cleaned = strip_thinking_block(raw)
    # Must keep at least one alphanumeric token, else BM25 gets an empty/garbage query.
    if not cleaned or not any(ch.isalnum() for ch in cleaned):
        return question

    if len(cleaned) > _MAX_REFINED_QUERY_CHARS:
        cleaned = cleaned[:_MAX_REFINED_QUERY_CHARS].strip()

    return cleaned
