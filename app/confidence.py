"""
app/confidence.py — Hybrid confidence scoring (CONF1–CONF3).

Responsibility: compute a deterministic numerical confidence score from three
property validators, then band it using the §9 thresholds.  The LLM never
sets the number — it may only ever produce the rationale string (CONF2).

The score is the equal-weight mean of three bounded [0,1] validators:
  1. coverage          — fraction of the question's significant tokens present
                         in the union of the retrieved chunk texts.
  2. grounded          — 1.0 if grounding.grounded else 0.0.
  3. retrieval_dominance — top1/(top1+top2) of the chunks' bm25_scores
                           (1.0 if only one positive chunk; 0.0 if none).

The rationale string is a deterministic offline template.  A live-lane LLM
rationale is a documented future extension — not built here (no dead code).

CONF1 — score computed only from property validators; identical inputs → identical score.
CONF2 — score is invariant to the rationale (computed in pure helper _compute_score()).
CONF3 — confidence_band() bands via §9 thresholds (no inline magic numbers).

Import-safe: no side effects at import — no network, no .env, no data/* read, no
client constructed.
"""

from __future__ import annotations

from app.config import (
    CONFIDENCE_AUTO_THRESHOLD,
    CONFIDENCE_REVIEW_THRESHOLD,
)
from app.draft import GroundingResult, _significant_tokens
from app.schema import ConfidenceResult, RetrievedChunk


# ---------------------------------------------------------------------------
# Pure score helper — the only place the number is produced (CONF2 contract)
# ---------------------------------------------------------------------------

def _compute_score(
    chunks: list[RetrievedChunk],
    grounding: GroundingResult,
    question: str,
) -> float:
    """Compute the deterministic confidence score from three property validators.

    Returns the equal-weight mean of:
      coverage            — fraction of the question's significant tokens in the
                            union of retrieved chunk texts.
      grounded            — 1.0 / 0.0 from the Stage-3 grounding gate.
      retrieval_dominance — top1 / (top1 + top2) BM25-score ratio.

    All three validators are bounded [0, 1].  The mean is therefore [0, 1].

    This function is PURE: it reads only its arguments; no I/O, no randomness,
    no model call.  Tests prove that removing or replacing the rationale string
    does not change the value returned here (CONF2).
    """
    # ---- Validator 1: coverage ------------------------------------------------
    # Fraction of the question's significant tokens present in any retrieved chunk.
    question_tokens = _significant_tokens(question)
    if not question_tokens:
        # Vacuously covered — no significant content to check against.
        coverage = 1.0
    else:
        # Build the union of all chunk texts (include chunk question text where present).
        chunk_union_text = " ".join(
            ((c.question + " " if c.question else "") + c.answer) for c in chunks
        )
        chunk_tokens = _significant_tokens(chunk_union_text)
        overlap = question_tokens.intersection(chunk_tokens)
        coverage = len(overlap) / len(question_tokens)

    # ---- Validator 2: grounded -----------------------------------------------
    grounded_val = 1.0 if grounding.grounded else 0.0

    # ---- Validator 3: retrieval_dominance ------------------------------------
    # top1 / (top1 + top2).  Handles edge cases cleanly.
    scores = sorted((c.bm25_score for c in chunks), reverse=True)
    positive_scores = [s for s in scores if s > 0.0]

    if len(positive_scores) == 0:
        retrieval_dominance = 0.0
    elif len(positive_scores) == 1:
        retrieval_dominance = 1.0
    else:
        top1, top2 = positive_scores[0], positive_scores[1]
        total = top1 + top2
        retrieval_dominance = top1 / total if total > 0.0 else 0.0

    # ---- Equal-weight mean ---------------------------------------------------
    return (coverage + grounded_val + retrieval_dominance) / 3.0


# ---------------------------------------------------------------------------
# score_confidence() — the graded contract (brief §1)
# ---------------------------------------------------------------------------

def score_confidence(
    chunks: list[RetrievedChunk],
    grounding: GroundingResult,
    question: str,
) -> ConfidenceResult:
    """Compute and return the hybrid ConfidenceResult for a questionnaire item.

    The numerical score comes ONLY from _compute_score() (three deterministic
    property validators).  The LLM never touches the number (CONF1/CONF2).

    The rationale is a deterministic offline template string describing the three
    signal values — no model call, no dead code (live-lane LLM rationale is a
    documented future extension that is NOT wired here).

    Parameters
    ----------
    chunks:
        The list of RetrievedChunk objects returned by retrieve() for this item.
        bm25_score must be populated (set by the retrieval stage).
    grounding:
        The GroundingResult from grounding_check() — carries .grounded (bool).
    question:
        The original question text from the QuestionnaireItem — used for the
        coverage validator.

    Returns
    -------
    ConfidenceResult
        .score    — float in [0, 1], purely deterministic.
        .rationale — explanatory template string; does NOT affect score or routing.
    """
    score = _compute_score(chunks, grounding, question)

    # Deterministic offline rationale — a template describing the signals.
    # Changing or removing this string does not change .score (CONF2).
    scores_sorted = sorted((c.bm25_score for c in chunks), reverse=True)
    positive = [s for s in scores_sorted if s > 0.0]
    top1 = positive[0] if positive else 0.0
    top2 = positive[1] if len(positive) > 1 else 0.0

    question_tokens = _significant_tokens(question)
    if not question_tokens:
        coverage_val = 1.0
    else:
        chunk_union_text = " ".join(
            ((c.question + " " if c.question else "") + c.answer) for c in chunks
        )
        chunk_tokens = _significant_tokens(chunk_union_text)
        overlap = question_tokens.intersection(chunk_tokens)
        coverage_val = len(overlap) / len(question_tokens)

    grounded_val_r = 1.0 if grounding.grounded else 0.0
    rd_sum = top1 + top2
    rd_val = (top1 / rd_sum) if rd_sum > 0.0 else 0.0
    rationale = (
        f"Confidence {score:.3f} = mean("
        f"coverage={coverage_val:.3f}, "
        f"grounded={grounded_val_r:.1f}, "
        f"retrieval_dominance={rd_val:.3f}"
        f"). "
        f"Retrieved {len(chunks)} chunk(s); top BM25 score {top1:.4f}; "
        f"grounding gate: {'PASS' if grounding.grounded else 'FAIL'}."
    )

    return ConfidenceResult(score=score, rationale=rationale)


# ---------------------------------------------------------------------------
# confidence_band() — the graded contract (brief §1; CONF3)
# ---------------------------------------------------------------------------

def confidence_band(score: float) -> str:
    """Map a confidence score to a band string.

    Bands (thresholds from §9 — no inline magic numbers):
      score >= CONFIDENCE_AUTO_THRESHOLD  → "auto"
      score <  CONFIDENCE_REVIEW_THRESHOLD → "review"   (low confidence)
      in-between                           → "review"   (conservative — CONF3)

    Parameters
    ----------
    score : float
        A value in [0, 1] as returned by score_confidence().

    Returns
    -------
    "auto" or "review"
    """
    if score >= CONFIDENCE_AUTO_THRESHOLD:
        return "auto"
    # Both below-threshold and in-between cases → "review" (conservative)
    return "review"
