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

from app.config import MAX_REFINED_QUERY_CHARS

if TYPE_CHECKING:  # avoid a runtime import cycle with app/llm.py (which imports this util)
    from app.llm import LLMProvider


# ---------------------------------------------------------------------------
# Deterministic <thinking> strip harness (named patterns — no magic literals inline)
# ---------------------------------------------------------------------------

# A single opening OR closing <thinking> tag (with or without attributes; tolerant of a
# malformed close like `</thinking foo>`). group(1) == "/" marks a close tag. The strip is
# a DEPTH-AWARE scan over these tags rather than a non-greedy regex, so it correctly
# distinguishes SEPARATE blocks (keep the content between them) from NESTED blocks (drop the
# whole outer block) — a non-greedy `.*?` leaked the outer block's tail on nested tags.
_THINKING_TAG_RE = re.compile(r"<(/?)thinking\b[^>]*>", re.IGNORECASE)


def strip_thinking_block(text: str) -> str:
    """Remove <thinking>...</thinking> reasoning from `text`, returning the clean remainder.

    Deterministic and total. Depth-aware so it handles every shape:
      - well-formed blocks (single or multiple — content BETWEEN separate blocks is kept);
      - NESTED blocks (`<thinking>a<thinking>b</thinking>c</thinking>` → the whole outer
        block, including `c`, is dropped — fixes the prior non-greedy leak);
      - a dangling unclosed <thinking> (everything from the outermost open tag to end is
        dropped → safe);
      - stray closing tags with no open (the tag is removed, surrounding text kept).
    Returns the stripped remainder; an empty string if nothing usable remains (callers
    fall back to the original question).
    """
    if not text:
        return ""
    kept: list[str] = []
    depth = 0
    last = 0  # start of the next run of text to keep
    for m in _THINKING_TAG_RE.finditer(text):
        is_close = m.group(1) == "/"
        if not is_close:
            if depth == 0:
                kept.append(text[last:m.start()])  # text before the outermost open tag
            depth += 1
        else:
            if depth > 0:
                depth -= 1
                if depth == 0:
                    last = m.end()  # resume keeping text after the outermost close tag
            else:
                kept.append(text[last:m.start()])  # stray close: drop the tag, keep text
                last = m.end()
    if depth == 0:
        kept.append(text[last:])  # trailing text after the last balanced close (or no tags)
    # depth > 0 ⇒ dangling open: everything from the outermost open onward is already dropped.
    # Join with a single space so each removed region acts as a token boundary (matches the
    # prior regex's " " substitution) — otherwise `AES<thinking>r</thinking>TLS` would fuse to
    # `AESTLS`. Internal whitespace/newlines in each kept run are preserved (only ONE space is
    # inserted per removed span), so the defensive strip on a multi-line draft answer is safe.
    return " ".join(kept).strip()


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

    if len(cleaned) > MAX_REFINED_QUERY_CHARS:
        cleaned = cleaned[:MAX_REFINED_QUERY_CHARS].strip()

    return cleaned
