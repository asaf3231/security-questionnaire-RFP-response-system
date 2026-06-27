"""
app/confidence.py — Hybrid confidence scoring (CONF1–CONF3).

Responsibility: compute a deterministic numerical confidence score from three
property validators, then band it using the §9 thresholds.  The LLM never
sets the number — it may only ever produce the rationale string (CONF2).

The score is the equal-weight mean of three bounded [0,1] validators:
  1. coverage          — fraction of the question's significant tokens present
                         in the union of the retrieved chunk texts.
  2. grounded          — 1.0 if grounding.grounded else 0.0.
  3. retrieval_dominance — when ≥ 2 positive-score chunks: top1/(top1+top2).
                           when exactly 1 positive chunk: = coverage (no
                           unearned corroboration bonus for weak single-chunk
                           answers — Stage 7r fix, D-S7r).
                           when 0 positive chunks: 0.0.

The rationale string is a deterministic offline template.  A live-lane LLM
rationale is a documented future extension — not built here (no dead code).

Stage 7 refactor (D-S7): coverage and retrieval_dominance are computed ONCE in
the new private _compute_components() helper and reused by score_confidence() for
both the numeric score and the rationale string — no duplicate calculation, no
possible drift between the reported number and the rationale prose.

Stage 7r fix (D-S7r): when there is exactly one positive-score chunk,
retrieval_dominance is now = coverage (previously 1.0, which gave an unearned
corroboration bonus to weak single-chunk answers). Multi-chunk (npos≥2) and
zero-positive cases are UNCHANGED.

_compute_score() signature is UNCHANGED (still returns float) so existing tests
continue to pass unchanged.  score_confidence() now calls _compute_components()
internally.

CONF1 — score computed only from property validators; identical inputs → identical score.
CONF2 — score is invariant to the rationale (computed via _compute_score()).
CONF3 — confidence_band() bands via §9 thresholds (no inline magic numbers).

Import-safe: no side effects at import — no network, no .env, no data/* read, no
client constructed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import (
    CONFIDENCE_AUTO_THRESHOLD,
    CONFIDENCE_REVIEW_THRESHOLD,
)
from app.draft import GroundingResult, _significant_tokens
from app.schema import ConfidenceResult, RetrievedChunk


# ---------------------------------------------------------------------------
# Internal component carrier — avoids duplicate computation (Stage 7 refactor)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ScoreComponents:
    """The three [0,1] property-validator values, raw BM25 values, and final score.

    Used internally so score_confidence() can build the rationale from the EXACT
    same values used to compute the score — no re-deriving, no possible drift.
    """
    coverage: float
    grounded_val: float
    retrieval_dominance: float
    score: float
    top1: float     # top BM25 score (for the rationale)
    top2: float     # second-highest BM25 score (for the rationale)


# ---------------------------------------------------------------------------
# Private components helper — single point of truth for all three validators
# ---------------------------------------------------------------------------

def _compute_components(
    chunks: list[RetrievedChunk],
    grounding: GroundingResult,
    question: str,
) -> _ScoreComponents:
    """Compute the deterministic confidence components and their equal-weight mean.

    Called by both _compute_score() (backward-compat float interface) and
    score_confidence() (uses components for the rationale).  Single source of
    truth for all three property validators.

    This function is PURE: no I/O, no randomness, no model call.
    """
    # ---- Validator 1: coverage -----------------------------------------------
    question_tokens = _significant_tokens(question)
    if not question_tokens:
        coverage = 1.0
    else:
        chunk_union_text = " ".join(
            ((c.question + " " if c.question else "") + c.answer) for c in chunks
        )
        chunk_tokens = _significant_tokens(chunk_union_text)
        overlap = question_tokens.intersection(chunk_tokens)
        coverage = len(overlap) / len(question_tokens)

    # ---- Validator 2: grounded -----------------------------------------------
    grounded_val = 1.0 if grounding.grounded else 0.0

    # ---- Validator 3: retrieval_dominance ------------------------------------
    scores = sorted((c.bm25_score for c in chunks), reverse=True)
    positive_scores = [s for s in scores if s > 0.0]

    if len(positive_scores) == 0:
        retrieval_dominance = 0.0
        top1, top2 = 0.0, 0.0
    elif len(positive_scores) == 1:
        # Stage 7r fix (D-S7r): a single positive-score chunk gives no
        # corroboration bonus — retrieval_dominance is bounded by coverage
        # so weak single-chunk answers are penalised (eval-006 is the
        # canonical example: qcov=0.111, formerly retrieval_dominance=1.0).
        # Multi-chunk (npos≥2) and zero-positive cases are UNCHANGED.
        retrieval_dominance = coverage
        top1, top2 = positive_scores[0], 0.0
    else:
        top1, top2 = positive_scores[0], positive_scores[1]
        total = top1 + top2
        retrieval_dominance = top1 / total if total > 0.0 else 0.0

    # ---- Equal-weight mean ---------------------------------------------------
    score = (coverage + grounded_val + retrieval_dominance) / 3.0

    return _ScoreComponents(
        coverage=coverage,
        grounded_val=grounded_val,
        retrieval_dominance=retrieval_dominance,
        score=score,
        top1=top1,
        top2=top2,
    )


# ---------------------------------------------------------------------------
# Pure score helper — the only place the number is produced (CONF2 contract)
# Unchanged signature: still returns float for backward compatibility.
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

    Delegates to _compute_components() — the single source of truth for all three
    validators.  Signature unchanged from Stage 4 (returns float).
    """
    return _compute_components(chunks, grounding, question).score


# ---------------------------------------------------------------------------
# score_confidence() — the graded contract (brief §1)
# ---------------------------------------------------------------------------

def score_confidence(
    chunks: list[RetrievedChunk],
    grounding: GroundingResult,
    question: str,
) -> ConfidenceResult:
    """Compute and return the hybrid ConfidenceResult for a questionnaire item.

    The numerical score comes ONLY from _compute_components() → _compute_score()
    (three deterministic property validators).  The LLM never touches the number
    (CONF1/CONF2).

    The rationale is a deterministic offline template string describing the three
    signal values — no model call, no dead code (live-lane LLM rationale is a
    documented future extension that is NOT wired here).

    Stage 7 refactor: coverage and retrieval_dominance are now computed ONCE via
    _compute_components() and reused here for the rationale — no duplicate
    calculation, no possible drift between the reported number and the rationale
    prose (D-S7 deferred follow-up cleared).

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
    # Compute once; reuse for both score and rationale (Stage 7 refactor, D-S7).
    components = _compute_components(chunks, grounding, question)
    score = components.score

    # Deterministic offline rationale — built from the EXACT component values
    # used to produce the score.  Changing or removing this string does not
    # change .score (CONF2).
    # Stage 7r: use components.retrieval_dominance directly (the exact value used
    # in the score) — this correctly reflects the npos==1 fix (dominance=coverage).
    rationale = (
        f"Confidence {score:.3f} = mean("
        f"coverage={components.coverage:.3f}, "
        f"grounded={components.grounded_val:.1f}, "
        f"retrieval_dominance={components.retrieval_dominance:.3f}"
        f"). "
        f"Retrieved {len(chunks)} chunk(s); top BM25 score {components.top1:.4f}; "
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
