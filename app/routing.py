"""
app/routing.py — The routing engine (RULE_HITM_REVIEW_TRIGGER chokepoint).

Responsibility: given a questionnaire item, its retrieved chunks, the confidence
result, and the loaded policy_tags, decide whether to route the item for human
review and to which queue — and why.

Four routing triggers (first match sets the reason_code — precedence enforced):
  1. High-risk tag   — item.topic_tags ∩ high_risk_tags → ROUTED_HIGH_RISK
  2. Ambiguity       — top1−top2 BM25 gap < AMBIGUITY_SCORE_MARGIN → ROUTED_AMBIGUOUS
  3. Low confidence  — score < CONFIDENCE_REVIEW_THRESHOLD → ROUTED_LOW_CONFIDENCE
  4. Sensitivity     — any chunk sensitivity ∈ {internal, restricted} → ROUTED_SENSITIVE
                       (lowest precedence; only fires when triggers 1–3 did not)

Queue resolution for triggers 2/3:
  - Iterate item.topic_tags in declaration order; return the first tag that has an
    entry in policy_tags["routing_map"] (deterministic).
  - If no tag maps → DEFAULT_REVIEWER_QUEUE (§9 fallback; never hardcoded inline).
Queue resolution for trigger 1:
  - The matched high-risk tag is looked up in the routing_map directly.

Queues are NEVER hardcoded — always resolved from the loaded policy map or the §9
default constant (ROUTE3).

RULE_HITM_REVIEW_TRIGGER enforced here (the single chokepoint).
Audit reason-codes ROUTED_HIGH_RISK, ROUTED_AMBIGUOUS, ROUTED_LOW_CONFIDENCE are
returned in RoutingDecision.reason_code for the pipeline/audit layer (Stage 5).
SENSITIVITY_GATE cross-check on routing is handled at export (Stage 5); this module
emits the routing decision only.

Import-safe: no side effects at import — no network, no .env, no data/* read, no
client constructed.
"""

from __future__ import annotations

from app.config import (
    AMBIGUITY_SCORE_MARGIN,
    CONFIDENCE_REVIEW_THRESHOLD,
    DEFAULT_REVIEWER_QUEUE,
    HIGH_RISK_TAGS,
    ROUTED_AMBIGUOUS,
    ROUTED_HIGH_RISK,
    ROUTED_LOW_CONFIDENCE,
    ROUTED_SENSITIVE,
    ROUTED_UNGROUNDED,
    RULE_HITM_REVIEW_TRIGGER,
    SENSITIVITY_REVIEW_QUEUE,
)

# The set of sensitivity values that trigger the 4th (lowest-priority) routing trigger.
# Named constant — no inline literal (CLAUDE.md §8 / brief §1 guidance).
_SENSITIVE_VALUES: frozenset[str] = frozenset({"internal", "restricted"})
from app.schema import ConfidenceResult, QuestionnaireItem, RetrievedChunk, RoutingDecision


# ---------------------------------------------------------------------------
# Queue resolution helpers
# ---------------------------------------------------------------------------

def _resolve_queue(topic_tags: list[str], routing_map: dict[str, str]) -> str:
    """Return the reviewer queue for the first tag that maps in routing_map.

    Iterates topic_tags in declaration order (deterministic).
    Falls back to DEFAULT_REVIEWER_QUEUE when no tag maps.
    Never hardcodes a queue string.
    """
    for tag in topic_tags:
        if tag in routing_map:
            return routing_map[tag]
    return DEFAULT_REVIEWER_QUEUE


def _resolve_queue_for_high_risk_tag(
    matched_tag: str,
    routing_map: dict[str, str],
) -> str:
    """Return the reviewer queue for a matched high-risk tag.

    The matched tag is looked up directly in the routing_map.
    Falls back to DEFAULT_REVIEWER_QUEUE if (unusually) not present.
    """
    return routing_map.get(matched_tag, DEFAULT_REVIEWER_QUEUE)


# ---------------------------------------------------------------------------
# route_for_review() — the graded contract (brief §2; RULE_HITM_REVIEW_TRIGGER)
# ---------------------------------------------------------------------------

def route_for_review(
    item: QuestionnaireItem,
    chunks: list[RetrievedChunk],
    confidence: ConfidenceResult,
    policy_tags: dict,
    *,
    grounded: bool = True,
) -> RoutingDecision:
    """Decide whether to route an item for human review.

    Applies the three routing triggers in precedence order (first match wins).
    Returns a RoutingDecision with should_route, queue, reason_code, and rule.

    Trigger precedence:
      1. High-risk tag  (ROUTED_HIGH_RISK)    — checked first; ignores score.
      2. Ambiguity      (ROUTED_AMBIGUOUS)    — top1−top2 gap < AMBIGUITY_SCORE_MARGIN.
      3. Low confidence (ROUTED_LOW_CONFIDENCE) — score < CONFIDENCE_REVIEW_THRESHOLD.
      4. Sensitivity    (ROUTED_SENSITIVE)    — any chunk sensitivity ∈ {internal, restricted};
                                               lowest precedence (fires only if 1–3 did not).

    When no trigger fires → RoutingDecision(should_route=False, queue=None, ...).

    Parameters
    ----------
    item:
        The questionnaire item being evaluated.
    chunks:
        The list of RetrievedChunk objects returned by retrieve() for this item.
        Sorted by bm25_score descending is assumed (as retrieve() guarantees).
    confidence:
        The ConfidenceResult from score_confidence().
    policy_tags:
        The dict returned by app.kb.load_policy_tags(); must contain:
          "high_risk_tags": list[str]   — overrides the §9 HIGH_RISK_TAGS default.
          "routing_map": dict[str, str] — tag → reviewer queue mapping.

    Returns
    -------
    RoutingDecision
        should_route  — True if any trigger fired.
        queue         — the reviewer queue string, or None if no trigger.
        reason_code   — one of ROUTED_HIGH_RISK / ROUTED_AMBIGUOUS /
                        ROUTED_LOW_CONFIDENCE / None.
        rule          — RULE_HITM_REVIEW_TRIGGER if routed, else None.
    """
    routing_map: dict[str, str] = policy_tags.get("routing_map", {})
    # Use the policy_tags high_risk_tags if present, otherwise fall back to §9 constant.
    high_risk_tags: list[str] = policy_tags.get("high_risk_tags", HIGH_RISK_TAGS)

    # ---- Trigger 1: High-risk tag -------------------------------------------
    for tag in item.topic_tags:
        if tag in high_risk_tags:
            queue = _resolve_queue_for_high_risk_tag(tag, routing_map)
            return RoutingDecision(
                should_route=True,
                queue=queue,
                reason_code=ROUTED_HIGH_RISK,
                rule=RULE_HITM_REVIEW_TRIGGER,
            )

    # ---- Trigger 2: Ambiguity -----------------------------------------------
    # top1 − top2 < AMBIGUITY_SCORE_MARGIN when ≥2 chunks are available.
    bm25_scores = sorted((c.bm25_score for c in chunks), reverse=True)
    if len(bm25_scores) >= 2:
        top1, top2 = bm25_scores[0], bm25_scores[1]
        gap = top1 - top2
        if gap < AMBIGUITY_SCORE_MARGIN:
            queue = _resolve_queue(item.topic_tags, routing_map)
            return RoutingDecision(
                should_route=True,
                queue=queue,
                reason_code=ROUTED_AMBIGUOUS,
                rule=RULE_HITM_REVIEW_TRIGGER,
            )

    # ---- Trigger 3: Low confidence ------------------------------------------
    if confidence.score < CONFIDENCE_REVIEW_THRESHOLD:
        queue = _resolve_queue(item.topic_tags, routing_map)
        return RoutingDecision(
            should_route=True,
            queue=queue,
            reason_code=ROUTED_LOW_CONFIDENCE,
            rule=RULE_HITM_REVIEW_TRIGGER,
        )

    # ---- Trigger 4: Sensitivity (lowest precedence) -------------------------
    # If any retrieved chunk carries a sensitivity that warrants human review
    # (internal or restricted) and none of the higher-priority triggers fired,
    # route to the sensitivity reviewer queue.
    if any(c.sensitivity in _SENSITIVE_VALUES for c in chunks):
        return RoutingDecision(
            should_route=True,
            queue=SENSITIVITY_REVIEW_QUEUE,
            reason_code=ROUTED_SENSITIVE,
            rule=RULE_HITM_REVIEW_TRIGGER,
        )

    # ---- Trigger 5 [DN-QA50 PR-1]: Ungrounded draft — absolute lowest precedence ----
    # A draft that failed the grounding gate (text = UNGROUNDED_PLACEHOLDER) must still
    # reach a human even when none of triggers 1–4 fired (RULE_GROUNDED_ONLY: "⇒ placeholder
    # + route"). Placed LAST so it never relabels an item another trigger already caught;
    # the default grounded=True keeps every pre-PR-1 caller byte-identical.
    if not grounded:
        queue = _resolve_queue(item.topic_tags, routing_map)
        return RoutingDecision(
            should_route=True,
            queue=queue,
            reason_code=ROUTED_UNGROUNDED,
            rule=RULE_HITM_REVIEW_TRIGGER,
        )

    # ---- No trigger fired ---------------------------------------------------
    return RoutingDecision(
        should_route=False,
        queue=None,
        reason_code=None,
        rule=None,
    )
