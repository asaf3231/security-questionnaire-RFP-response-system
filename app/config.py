"""
app/config.py — the ONLY home for magic values.

Responsibility: defines all §9 named constants, RULE_* registry strings, byte-exact literals,
the lazy Claude client singleton (_get_claude()), and the load_env() helper.

RULE_* enforced here: RULE_NO_SECRET (API key never hardcoded; only via env).

Import-safe: zero side effects at import — no .env read, no client built, no data/* read,
no network, no file written. All clients are lazy singletons (module-global None, constructed
only on first call via _get_claude()).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Retrieval (Stage 2) — rank_bm25, deterministic, paragraph/approved-answer chunks
# ---------------------------------------------------------------------------
RETRIEVAL_TOP_K: int = 5          # chunks returned into the backpack (Recall-first; tune in Stage 2)
BM25_K1: float = 1.5              # rank_bm25 term-frequency saturation
BM25_B: float = 0.75              # rank_bm25 length normalization
RECALL_AT_K_TARGET: float = 0.90  # acceptance bar for Recall@K on labeled fixtures

# ---------------------------------------------------------------------------
# Confidence + routing (Stage 4) — hybrid: deterministic gate, LLM rationale only
# ---------------------------------------------------------------------------
CONFIDENCE_AUTO_THRESHOLD: float = 0.75    # >= this AND no trigger → confident auto-draft
CONFIDENCE_REVIEW_THRESHOLD: float = 0.50  # <  this → mandatory human review
GROUNDING_MIN_CITATIONS: int = 1           # min retrieved chunks an asserted answer must cite
AMBIGUITY_SCORE_MARGIN: float = 0.10       # top1−top2 BM25-score gap below this → "ambiguous"

# ---------------------------------------------------------------------------
# Draft model (Stage 3; LIVE lane only — offline path uses MockLLM)
# ---------------------------------------------------------------------------
DRAFT_MODEL: str = "claude-sonnet-4-6"   # pinned at Stage 1 (OQ-1); opus-4-8 swappable (graded contract)
MAX_OUTPUT_TOKENS: int = 1024
DRAFT_TEMPERATURE: float = 0.0            # determinism in the live lane

# Query refinement (Stage 10; LIVE lane only) — bounds on the QUERY_REFINEMENT call/output
REFINE_MAX_TOKENS: int = 256              # a refined query is short; bound the refinement call
MAX_REFINED_QUERY_CHARS: int = 512        # cap a refined query so a runaway response can't blow up retrieval

# ---------------------------------------------------------------------------
# Grounding (Stage 3) — RULE_GROUNDED_ONLY
# ---------------------------------------------------------------------------
GROUNDING_COVERAGE_MIN: float = 0.5   # fraction of draft's significant content tokens that must
                                       # appear in the union of cited chunk texts (D-S3)
GROUNDING_QUESTION_COVERAGE_MIN: float = 0.30  # fraction of the question's significant tokens
                                                # that must appear in the cited chunks; below this
                                                # the cited evidence does not address the question
                                                # (additive relevance gate — Stage 7r, D-S7r).
                                                # Clean gap: eval-006 qcov 0.111 < 0.30 ≤ 0.625
                                                # (minimum across all legitimate items).
GROUNDING_FAIL: str = "GROUNDING_FAIL"  # §5.1 audit reason-code emitted at app/draft.py chokepoint

# ---------------------------------------------------------------------------
# Stage 4 audit reason-codes (§5.1) — RULE_HITM_REVIEW_TRIGGER + RULE_NO_SELF_APPROVE
# ---------------------------------------------------------------------------
ROUTED_HIGH_RISK: str = "ROUTED_HIGH_RISK"          # high-risk tag trigger (app/routing.py)
ROUTED_AMBIGUOUS: str = "ROUTED_AMBIGUOUS"           # ambiguity trigger (app/routing.py)
ROUTED_LOW_CONFIDENCE: str = "ROUTED_LOW_CONFIDENCE" # low-confidence trigger (app/routing.py)
SELF_APPROVE_BLOCKED: str = "SELF_APPROVE_BLOCKED"   # agent self-approve blocked (app/state.py)

# ---------------------------------------------------------------------------
# Stage 5 audit reason-codes (§5.1) — RULE_SENSITIVITY_GATE + RULE_NO_EXTERNAL_SEND
# ---------------------------------------------------------------------------
SENSITIVITY_HOLD: str = "SENSITIVITY_HOLD"            # sensitivity gate held item (app/export.py)
EXTERNAL_SEND_BLOCKED: str = "EXTERNAL_SEND_BLOCKED"  # local-only export confirmed (app/export.py)

ERROR_TERMINAL: str = "ERROR_TERMINAL"           # safe-terminal audit reason-code (app/pipeline.py)

# Fallback reviewer queue when no item topic_tag maps to the policy routing_map
# Must be ∈ REVIEWER_QUEUES; kept in §9 (not in data) — avoids editing Stage-1 fixtures (D-S4).
DEFAULT_REVIEWER_QUEUE: str = "engineering"

# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
RANDOM_SEED: int = 42   # seeds MockLLM + any sampling; the offline suite is reproducible

# ---------------------------------------------------------------------------
# Routing / queues / tags (Stages 1 & 4)
# ---------------------------------------------------------------------------
REVIEWER_QUEUES: list[str] = ["security", "legal", "engineering", "gtm", "compliance"]

# Stage 7 — Option-A sensitivity routing (Asaf-authorized graded additions)
SENSITIVITY_REVIEW_QUEUE: str = "compliance"  # must ∈ REVIEWER_QUEUES
ROUTED_SENSITIVE: str = "ROUTED_SENSITIVE"    # 4th RULE_HITM_REVIEW_TRIGGER reason-code
# DN-QA50 PR-1 (Asaf-ratified graded addition): 5th/lowest-precedence trigger — an ungrounded
# draft must still route to a human even when no other trigger fired (RULE_GROUNDED_ONLY).
ROUTED_UNGROUNDED: str = "ROUTED_UNGROUNDED"   # 5th RULE_HITM_REVIEW_TRIGGER reason-code (app/routing.py)
HIGH_RISK_TAGS: list[str] = ["legal", "security"]              # presence → mandatory routing
SENSITIVITY_TAGS: list[str] = ["public", "internal", "restricted"]  # internal/restricted never auto-export

# ---------------------------------------------------------------------------
# Item state machine (Stage 4)
# ---------------------------------------------------------------------------
ITEM_STATES: list[str] = [
    "INTAKE",
    "RETRIEVED",
    "DRAFTED",
    "SCORED",
    "ROUTED_FOR_REVIEW",
    "REVIEW_APPROVED",
    "REVIEW_REJECTED",
    "APPROVED",
    "EXPORTED",
]

# ---------------------------------------------------------------------------
# Byte-exact graded literals (CLAUDE.md §9 — do NOT alter)
# ---------------------------------------------------------------------------
REVIEW_BANNER: str = "⚠️ PENDING HUMAN REVIEW — NOT APPROVED FOR EXTERNAL RELEASE"
UNGROUNDED_PLACEHOLDER: str = "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"

# ---------------------------------------------------------------------------
# The agent's callable functions (name == schema name == dispatch key)
# ---------------------------------------------------------------------------
AGENT_TOOLS: list[str] = [
    "retrieve",
    "assemble_context",
    "draft_answer",
    "score_confidence",
    "route_for_review",
    "update_status",
    "write_audit",
    "export_response",
]

# Import-time assertion: all AGENT_TOOLS names must be unique
assert len(AGENT_TOOLS) == len(set(AGENT_TOOLS)), (
    "AGENT_TOOLS contains duplicate entries — tool dispatch would be ambiguous"
)

# ---------------------------------------------------------------------------
# Grep-enforceable governance identifiers (CLAUDE.md §5)
# Each is its own string value so grep finds both the definition and the usage site.
# ---------------------------------------------------------------------------
RULE_GROUNDED_ONLY: str = "RULE_GROUNDED_ONLY"
RULE_NO_SELF_APPROVE: str = "RULE_NO_SELF_APPROVE"
RULE_HITM_REVIEW_TRIGGER: str = "RULE_HITM_REVIEW_TRIGGER"
RULE_NO_EXTERNAL_SEND: str = "RULE_NO_EXTERNAL_SEND"
RULE_SENSITIVITY_GATE: str = "RULE_SENSITIVITY_GATE"
RULE_NO_SECRET: str = "RULE_NO_SECRET"
RULE_NO_REAL_PII: str = "RULE_NO_REAL_PII"
RULE_NO_EVAL_CONTAMINATION: str = "RULE_NO_EVAL_CONTAMINATION"
RULE_NO_FABRICATED_METRIC: str = "RULE_NO_FABRICATED_METRIC"
RULE_AUDIT_COMPLETE: str = "RULE_AUDIT_COMPLETE"
RULE_SAFE_TERMINAL: str = "RULE_SAFE_TERMINAL"

# ---------------------------------------------------------------------------
# Lazy Claude client singleton — NEVER constructed at import time
# ---------------------------------------------------------------------------
_claude_client = None  # module-global; remains None until _get_claude() is first called


def _get_claude():
    """Return the lazy Anthropic client singleton, constructing it on first call only.

    Called ONLY from the gated live lane (app/llm.py ClaudeLLM).
    Never called at import time. Requires ANTHROPIC_API_KEY in the environment.
    RULE_NO_SECRET: the key is read from os.environ, never hardcoded.
    """
    global _claude_client
    if _claude_client is None:
        import os
        import anthropic  # noqa: PLC0415 — import deferred intentionally
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it in your .env file and call load_env() before using the live lane."
            )
        _claude_client = anthropic.Anthropic(api_key=api_key)
    return _claude_client


def load_env() -> None:
    """Load .env into os.environ using python-dotenv.

    Called from CLI entry points / scripts only — NEVER at module import time.
    Idempotent: safe to call multiple times.
    """
    from dotenv import load_dotenv  # noqa: PLC0415 — deferred intentionally
    load_dotenv(override=False)
