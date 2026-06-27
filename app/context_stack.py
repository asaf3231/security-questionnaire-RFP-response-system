"""
app/context_stack.py — 4-layer context "backpack" assembler.

Responsibility: given a QuestionnaireItem and a list of retrieved KB chunks, build a
ContextStack (Instruction / Retrieval / Constraint / State) that is the ONLY context
the model sees. Nothing outside the passed-in retrieved chunks reaches the model (CTX1,
D-S3, RULE_GROUNDED_ONLY precondition).

QA checks this module satisfies:
  CTX1 — all 4 layers present; Retrieval layer = ONLY the passed chunks (no other KB content)
  CTX2 — Instruction layer carries explicit RFP/questionnaire handling rules
  CTX3 — Constraint layer injects a high-risk clause for high-risk items
  CTX4 — State layer carries "Question X of Y" + item's current pipeline state

Import-safe: no side effects at import — no network, no .env, no data/* read, no file written.
"""

from __future__ import annotations

from app.config import HIGH_RISK_TAGS
from app.schema import ContextStack, QuestionnaireItem, RetrievedChunk

# ---------------------------------------------------------------------------
# Named template constants (CTX2 / CTX3 — never inline prose in the function)
# These are this module's responsibility: the prompt/persona template lives here,
# not in config.py (which holds cross-cutting magic values, not prompt text).
# ---------------------------------------------------------------------------

INSTRUCTION_CONTEXT: str = (
    "You are Comet, an AI assistant that drafts grounded responses to RFP and security "
    "questionnaire items on behalf of a technology company.\n"
    "Rules:\n"
    "1. Draft your answer using ONLY the evidence in the Retrieval Context below.\n"
    "2. Cite every chunk you draw from by its [chunk_id] marker.\n"
    "3. If the Retrieval Context does not contain enough evidence to answer, say so explicitly "
    "and do not invent information.\n"
    "4. Write in clear, professional prose suitable for submission to a security or compliance "
    "review team.\n"
    "5. Do not speculate, fabricate, or extrapolate beyond what the retrieved evidence supports."
)

_CONSTRAINT_BASE: str = (
    "HARD CONSTRAINT: Answer ONLY from the Retrieval Context above. "
    "If the retrieved evidence does not support a complete answer, acknowledge the gap and "
    "do not invent or extrapolate. Cite every claim with its [chunk_id]."
)

_CONSTRAINT_HIGH_RISK_CLAUSE: str = (
    " ADDITIONAL CONSTRAINT: This item is flagged as HIGH-RISK (legal/security category). "
    "Do NOT assert a legal position, make compliance guarantees, or provide security assurances "
    "without a directly supporting approved document in the Retrieval Context. "
    "When in doubt, defer to human review rather than drafting a speculative answer."
)


def _has_high_risk_tag(item: QuestionnaireItem) -> bool:
    """Return True if the item carries at least one HIGH_RISK_TAGS tag."""
    item_tags = set(item.topic_tags)
    return bool(item_tags.intersection(HIGH_RISK_TAGS))


def _format_retrieval_entry(chunk: RetrievedChunk) -> str:
    """Format a single retrieved chunk as '[chunk_id] <text>' for the Retrieval layer.

    The text is the chunk's full content: question + answer (if question exists) or
    answer alone — matching the BM25 document text so citations are grounded in context
    that was actually ranked and returned.
    """
    if chunk.question:
        text = chunk.question + " " + chunk.answer
    else:
        text = chunk.answer
    return f"[{chunk.chunk_id}] {text}"


# ---------------------------------------------------------------------------
# assemble_context() — the graded contract (do NOT change signature; surface as DECISION-NEEDED)
# ---------------------------------------------------------------------------

def assemble_context(
    item: QuestionnaireItem,
    chunks: list[RetrievedChunk],
    *,
    item_number: int,
    total_items: int,
) -> ContextStack:
    """Assemble the 4-layer context stack for one questionnaire item.

    Parameters
    ----------
    item:
        The questionnaire item being answered.
    chunks:
        The retrieved KB chunks for this item (already filtered and ranked by retrieval.py).
        ONLY these chunks appear in the Retrieval layer — nothing else reaches the model (CTX1).
    item_number:
        1-based position of this item in the questionnaire (for the State layer).
    total_items:
        Total number of items in the questionnaire (for the State layer).

    Returns
    -------
    ContextStack
        A ContextStack with all 4 layers populated.
    """
    # Layer 1 — Instruction: explicit RFP/questionnaire handling rules + persona
    instruction = INSTRUCTION_CONTEXT

    # Layer 2 — Retrieval: ONLY the passed-in chunks, each formatted as "[chunk_id] text"
    # Nothing outside this list reaches the model (CTX1 / RULE_GROUNDED_ONLY precondition).
    retrieval = [_format_retrieval_entry(c) for c in chunks]

    # Layer 3 — Constraint: base hard boundary + high-risk clause when applicable (CTX3)
    constraint = _CONSTRAINT_BASE
    if _has_high_risk_tag(item):
        constraint += _CONSTRAINT_HIGH_RISK_CLAUSE

    # Layer 4 — State: position in questionnaire + current pipeline state (CTX4)
    state = (
        f"Question {item_number} of {total_items} | "
        f"Item ID: {item.item_id} | "
        f"Current state: INTAKE"
    )

    return ContextStack(
        instruction=instruction,
        retrieval=retrieval,
        constraint=constraint,
        state=state,
    )
