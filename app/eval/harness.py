"""
app/eval/harness.py — Offline deterministic evaluation harness (EVAL1–EVAL3).

Responsibility: run the full pipeline over held-out labeled eval fixtures and
compute four metrics — all from labeled inputs, never hardcoded.

Metrics:
  recall_at_k      — Recall@RETRIEVAL_TOP_K over recall_at_k_gold.json fixtures
                     (reuses app/eval/rubric.compute_recall_at_k — Stage 2 contract).
  grounding_rate   — fraction of eval cases whose grounding outcome matches the
                     expected_grounded label, PLUS the raw grounded fraction.
  routing_accuracy — fraction of eval cases whose routing decision (should_route,
                     queue, reason_code) matches the labeled expectation exactly.
  calibration      — matrix of confidence band × grounded outcome counts over the
                     held-out cases (e.g. counts of auto/review × grounded/ungrounded).

RULE_NO_FABRICATED_METRIC: every value is derived from compute_ functions applied to
  labeled fixtures; no number is hardcoded.  Grounding is determined by the REAL
  production grounding_check() / draft_answer() path (passing the question for the
  Stage 7r question-relevance gate) — never a simulator (Stage 7r governance fix,
  D-S7r: _simulate_grounding has been deleted).
RULE_NO_EVAL_CONTAMINATION: the eval harness reads the production KB read-only;
  it NEVER modifies data/kb/* or any production data file.  Held-out questions are
  distinct from the KB's own question fields (gold answers are not pre-seeded).

Import-safe: no side effects at import — no network, no .env, no data/* read, no
client constructed.  All data loading is deferred to run_eval().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import (
    RETRIEVAL_TOP_K,
    RULE_NO_EVAL_CONTAMINATION,
    RULE_NO_FABRICATED_METRIC,
)
from app.confidence import confidence_band, score_confidence
from app.draft import draft_answer, grounding_check
from app.eval.rubric import compute_recall_at_k
from app.schema import ConfidenceResult, QuestionnaireItem, RetrievedChunk


# ---------------------------------------------------------------------------
# Fixture paths (relative to repo root — pathlib, no hardcoded absolute paths)
# ---------------------------------------------------------------------------

def _fixtures_dir() -> Path:
    """Return the fixtures/eval/ directory (absolute, relative to this file)."""
    return Path(__file__).resolve().parent.parent.parent / "fixtures" / "eval"


def _load_eval_cases() -> list[dict[str, Any]]:
    """Load eval_cases.synthetic.json from fixtures/eval/.

    Each case has: item_id, question, topic_tags, expected_routed (bool),
    expected_queue (str|null), expected_reason (str|null), expected_grounded (bool).

    RULE_NO_FABRICATED_METRIC: every metric is derived from these labels,
    never asserted as a literal value.
    """
    path = _fixtures_dir() / "eval_cases.synthetic.json"
    if not path.exists():
        raise ValueError(
            f"eval_cases.synthetic.json not found at {path}; "
            "create fixtures/eval/eval_cases.synthetic.json before running eval."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("eval_cases.synthetic.json must be a JSON array")
    required = ("item_id", "question", "expected_routed", "expected_grounded")
    for i, rec in enumerate(raw):
        for field in required:
            if field not in rec:
                raise ValueError(
                    f"eval_cases.synthetic.json record {i} is missing field '{field}'"
                )
    return raw


def _load_recall_gold() -> list[dict[str, Any]]:
    """Load recall_at_k_gold.json from fixtures/eval/ for the Recall@K metric."""
    path = _fixtures_dir() / "recall_at_k_gold.json"
    if not path.exists():
        raise ValueError(f"recall_at_k_gold.json not found at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("recall_at_k_gold.json must be a JSON array")
    return raw


# ---------------------------------------------------------------------------
# Contamination guard — proves the eval is held-out (EVAL2 / LEAK4)
# ---------------------------------------------------------------------------

def check_no_contamination(
    eval_cases: list[dict[str, Any]],
    kb_chunks: list[RetrievedChunk],
) -> None:
    """Assert that no eval-case question appears verbatim as a KB chunk question.

    RULE_NO_EVAL_CONTAMINATION: the gold answer for an eval case must not be
    pre-seeded as a KB chunk that the retriever can find as its own evidence.

    Raises ValueError if contamination is detected.
    """
    kb_questions = {
        (c.question or "").strip().lower()
        for c in kb_chunks
        if c.question
    }
    for case in eval_cases:
        q_lower = case["question"].strip().lower()
        if q_lower in kb_questions:
            raise ValueError(
                f"RULE_NO_EVAL_CONTAMINATION violated: eval-case question "
                f"'{case['question'][:80]}' appears verbatim in the KB — "
                f"the gold answer is pre-seeded (contamination detected)."
            )


# ---------------------------------------------------------------------------
# run_eval() — the public interface (EVAL1–EVAL3)
# ---------------------------------------------------------------------------

def run_eval(
    *,
    retriever=None,
    provider=None,
    policy_tags: dict | None = None,
) -> dict[str, Any]:
    """Run the offline eval harness and return computed metrics.

    All four metrics are computed from labeled held-out fixtures:
      recall_at_k      — macro-average Recall@RETRIEVAL_TOP_K over recall_at_k_gold.json
      grounding_rate   — dict with 'match_rate' (correct grounding predictions)
                         and 'raw_grounded_rate' (fraction of cases where grounding=True)
      routing_accuracy — fraction of cases where routing decision exactly matches labels
      calibration      — dict of counts: {band: {'grounded': n, 'ungrounded': n}}

    Grounding is determined by the REAL production path — assemble_context() +
    draft_answer(question=...) / grounding_check(question=...) — so the eval reflects
    actual system behaviour, not a simulator.  This is the Stage 7r governance fix
    (D-S7r): _simulate_grounding has been deleted; no fake grounding in the harness.

    Parameters
    ----------
    retriever:
        Optional Retriever instance.  If None, a default Retriever over the
        production KB is built (read-only — never mutated).
    provider:
        Optional LLM provider.  Defaults to MockLLM() (offline, deterministic).
        The offline default is used for all eval runs (no network, no API key).
    policy_tags:
        Optional policy_tags dict.  If None, loaded from data/policy_tags.synthetic.json.

    Returns
    -------
    dict with keys: recall_at_k, grounding_rate, routing_accuracy, calibration.
    All values are computed from labeled inputs (RULE_NO_FABRICATED_METRIC).
    """
    # --- Lazy imports (import-safe at module level) ---
    from app.context_stack import assemble_context
    from app.kb import load_kb, load_policy_tags
    from app.llm import MockLLM
    from app.retrieval import Retriever
    from app.routing import route_for_review

    # Load the production KB read-only (never mutated — RULE_NO_EVAL_CONTAMINATION).
    kb_chunks = load_kb()
    if retriever is None:
        retriever = Retriever(kb_chunks)
    if policy_tags is None:
        policy_tags = load_policy_tags()
    if provider is None:
        provider = MockLLM()

    # --- Load labeled fixtures (the source of truth for all metrics) ---
    eval_cases = _load_eval_cases()
    recall_gold = _load_recall_gold()

    # --- Contamination check (EVAL2 / LEAK4 / RULE_NO_EVAL_CONTAMINATION) ---
    check_no_contamination(eval_cases, kb_chunks)

    # --- Metric 1: Recall@K (reuse Stage-2 rubric — EVAL1 / RET2) ---
    recall_at_k = compute_recall_at_k(recall_gold, k=RETRIEVAL_TOP_K)

    # --- Per-case evaluation loop ---
    grounding_matches: list[bool] = []
    raw_grounded: list[bool] = []
    routing_correct: list[bool] = []
    calibration_counts: dict[str, dict[str, int]] = {
        "auto": {"grounded": 0, "ungrounded": 0},
        "review": {"grounded": 0, "ungrounded": 0},
    }

    for idx, case in enumerate(eval_cases, start=1):
        question: str = case["question"]
        topic_tags: list[str] = case.get("topic_tags", [])
        expected_routed: bool = case["expected_routed"]
        expected_queue: str | None = case.get("expected_queue")
        expected_reason: str | None = case.get("expected_reason")
        expected_grounded: bool = case["expected_grounded"]

        # Retrieve chunks for this eval case (read-only; does not mutate KB)
        chunks = retriever.retrieve(
            question=question,
            topic_tags=topic_tags if topic_tags else None,
            top_k=RETRIEVAL_TOP_K,
        )

        # Determine grounding via the REAL production path (Stage 7r fix — D-S7r).
        # _simulate_grounding has been deleted.  We assemble the context stack and
        # call the real draft_answer(question=...) / grounding_check(question=...).
        # This means grounding_rate reflects factual system behaviour; the negative
        # case (eval-006) is honestly caught (grounded=False).
        item = QuestionnaireItem(
            item_id=case["item_id"],
            question=question,
            topic_tags=topic_tags,
        )
        context_stack = assemble_context(
            item,
            chunks,
            item_number=idx,
            total_items=len(eval_cases),
        )
        raw_draft = draft_answer(context_stack, provider=provider, question=question)
        grounding = grounding_check(raw_draft, context_stack, question=question)
        actual_grounded: bool = grounding.grounded

        # Grounding rate: does the real grounding outcome match the label?
        grounding_matches.append(actual_grounded == expected_grounded)
        raw_grounded.append(actual_grounded)

        # Confidence score (deterministic, no LLM call)
        conf: ConfidenceResult = score_confidence(chunks, grounding, question)
        band: str = confidence_band(conf.score)

        # Routing decision
        decision = route_for_review(item, chunks, conf, policy_tags)
        actual_routed = decision.should_route
        actual_queue = decision.queue
        actual_reason = decision.reason_code

        # Routing accuracy: exact match on all three routing fields
        routing_match = (
            actual_routed == expected_routed
            and actual_queue == expected_queue
            and actual_reason == expected_reason
        )
        routing_correct.append(routing_match)

        # Calibration: band × grounded outcome
        grounded_key = "grounded" if actual_grounded else "ungrounded"
        calibration_counts[band][grounded_key] += 1

    n = len(eval_cases)

    # --- Metric 2: Grounding rate ---
    grounding_rate = {
        "match_rate": sum(grounding_matches) / n if n > 0 else 0.0,
        "raw_grounded_rate": sum(raw_grounded) / n if n > 0 else 0.0,
    }

    # --- Metric 3: Routing accuracy ---
    routing_accuracy = sum(routing_correct) / n if n > 0 else 0.0

    # --- Metric 4: Calibration ---
    calibration = calibration_counts

    return {
        "recall_at_k": recall_at_k,
        "grounding_rate": grounding_rate,
        "routing_accuracy": routing_accuracy,
        "calibration": calibration,
        "n_eval_cases": n,
        "n_recall_gold": len(recall_gold),
        "rule_no_fabricated_metric": RULE_NO_FABRICATED_METRIC,
        "rule_no_eval_contamination": RULE_NO_EVAL_CONTAMINATION,
    }


# ---------------------------------------------------------------------------
# CLI entry point: `python -m app.eval.harness` or `make eval`
# ---------------------------------------------------------------------------

def _print_metrics(metrics: dict[str, Any]) -> None:
    """Print the eval metrics in a readable format."""
    print("\n=== Comet Offline Eval Harness ===")
    print(f"Eval cases    : {metrics['n_eval_cases']}")
    print(f"Recall@K gold : {metrics['n_recall_gold']} fixtures")
    print()
    print(f"recall_at_k       : {metrics['recall_at_k']:.4f}")
    grounding = metrics["grounding_rate"]
    print(
        f"grounding_rate    : match_rate={grounding['match_rate']:.4f}  "
        f"raw_grounded={grounding['raw_grounded_rate']:.4f}"
    )
    print(f"routing_accuracy  : {metrics['routing_accuracy']:.4f}")
    print()
    print("calibration (confidence_band × grounded outcome):")
    for band, counts in metrics["calibration"].items():
        print(f"  {band:8s}: grounded={counts['grounded']}  ungrounded={counts['ungrounded']}")
    print()
    print(f"Rules enforced: {metrics['rule_no_fabricated_metric']}  "
          f"{metrics['rule_no_eval_contamination']}")


if __name__ == "__main__":
    _metrics = run_eval()
    _print_metrics(_metrics)
