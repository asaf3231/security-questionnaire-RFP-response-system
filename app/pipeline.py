"""
app/pipeline.py — End-to-end orchestration pipeline for Comet (Stage 6).

Responsibility: wire all Stage 1–5 modules together into a single run_pipeline()
function that takes a loaded questionnaire and returns a PipelineResult containing
the ResponseDoc, per-item routing decisions, and error records.

Pipeline shape (CLAUDE.md §3.1):
  INTAKE → retrieve → RETRIEVED → assemble_context → draft_answer + grounding_check
        → DRAFTED → score_confidence → SCORED → route_for_review →
        (trigger fires)  → ROUTED_FOR_REVIEW  (agent stops here; human must act)
        (no trigger)     → SCORED             (confident draft; human must APPROVE)
  Every state transition + tool call is audited (RULE_AUDIT_COMPLETE).

RULE_SAFE_TERMINAL (PIPE2): every item runs inside a try/except. ANY component failure
(malformed chunk, empty retrieval, provider raise, validation error) → item placed in a
safe terminal state (ROUTED_FOR_REVIEW) with draft_text=UNGROUNDED_PLACEHOLDER, the error
message recorded in PipelineResult.errors[item_id], and an ERROR_TERMINAL audit event.
No uncaught exception may escape run_pipeline().

RULE_NO_SELF_APPROVE: the pipeline (agent) never transitions an item to APPROVED or
EXPORTED. Only run_demo.py's simulated human action (actor="human") does that.

Import-safe: no side effects at import — no network, no .env read, no client built,
no data/* read, no file written. All I/O is deferred to explicit function calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.audit import new_audit_event, write_audit
from app.config import (
    ERROR_TERMINAL,
    RULE_AUDIT_COMPLETE,
    RULE_SAFE_TERMINAL,
    UNGROUNDED_PLACEHOLDER,
)
from app.context_stack import assemble_context
from app.draft import draft_answer, grounding_check
from app.kb import load_kb, load_policy_tags
from app.llm import LLMProvider, MockLLM
from app.query_optimizer import refine_query
from app.retrieval import Retriever
from app.routing import route_for_review
from app.confidence import score_confidence
from app.schema import (
    Citation,
    ResponseDoc,
    ResponseDocItem,
    RoutingDecision,
)
from app.state import transition


# ---------------------------------------------------------------------------
# PipelineResult — the return type of run_pipeline()
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Return value of run_pipeline().

    Attributes
    ----------
    response_doc:
        The assembled ResponseDoc (one item per questionnaire item).
        Agent-side items sit at SCORED (confident) or ROUTED_FOR_REVIEW;
        the agent never transitions to APPROVED/EXPORTED.
    routing:
        Per-item routing decisions keyed by item_id.
    errors:
        Per-item error messages for items that hit RULE_SAFE_TERMINAL.
        item_id → error message string. Empty dict when no errors occurred.
    """
    response_doc: ResponseDoc
    routing: dict[str, RoutingDecision] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# run_pipeline() — the graded contract (PIPE1/PIPE2)
# ---------------------------------------------------------------------------

def run_pipeline(
    questionnaire: dict,
    *,
    provider: Optional[LLMProvider] = None,
    retriever: Optional[Retriever] = None,
    policy_tags: Optional[dict] = None,
    audit_log_path: Optional[Path] = None,
) -> PipelineResult:
    """Run the full Comet pipeline on a loaded questionnaire.

    Per-item chain (CLAUDE.md §3.1):
      INTAKE → retrieve → RETRIEVED → assemble_context → draft_answer → DRAFTED
             → score_confidence → SCORED → route_for_review
               • trigger fires  → transition(SCORED→ROUTED_FOR_REVIEW, actor="agent")
               • no trigger     → leave at SCORED (confident draft; awaits human APPROVED)

    Every state transition and tool call is audited (RULE_AUDIT_COMPLETE).

    RULE_SAFE_TERMINAL: any per-item failure → ROUTED_FOR_REVIEW +
    UNGROUNDED_PLACEHOLDER + ERROR_TERMINAL audit event; never an uncaught exception.

    RULE_NO_SELF_APPROVE: the pipeline never transitions to APPROVED or EXPORTED.

    Parameters
    ----------
    questionnaire:
        The dict returned by app.kb.load_questionnaire():
          {"questionnaire_id": str, "items": list[QuestionnaireItem]}
    provider:
        An LLMProvider to use for drafting. Defaults to MockLLM() (offline, deterministic).
        Pass ClaudeLLM() only from the gated live lane (make demo-live).
    retriever:
        A Retriever instance (index already built). Defaults to Retriever(load_kb()).
        Callers may pass a pre-built Retriever to share the index across runs.
    policy_tags:
        The dict returned by app.kb.load_policy_tags(). Defaults to load_policy_tags().
    audit_log_path:
        Optional explicit path for the audit JSONL. Defaults to the standard location.

    Returns
    -------
    PipelineResult
        Contains the ResponseDoc, per-item routing decisions, and per-item errors.
    """
    # --- Resolve defaults (deferred, never at import) ---
    if provider is None:
        provider = MockLLM()
    if retriever is None:
        retriever = Retriever(load_kb())
    if policy_tags is None:
        policy_tags = load_policy_tags()

    questionnaire_id: str = questionnaire["questionnaire_id"]
    items = questionnaire["items"]
    total = len(items)
    generated_at = datetime.now(timezone.utc).isoformat()

    doc_items: list[ResponseDocItem] = []
    routing_decisions: dict[str, RoutingDecision] = {}
    errors: dict[str, str] = {}

    for idx, item in enumerate(items, start=1):
        item_id = item.item_id

        try:
            # ----------------------------------------------------------------
            # 1. INTAKE — initial state; audit the tool call
            # ----------------------------------------------------------------
            current_state = "INTAKE"
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=None,
                    to_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={"tool": "intake", "question": item.question},
                ),
                log_path=audit_log_path,
            )

            # ----------------------------------------------------------------
            # 1b. QUERY_REFINEMENT (Stage 10) — optimize the search query via the LLM
            # BEFORE retrieval. MockLLM returns identity (offline determinism preserved);
            # ClaudeLLM expands with synonyms/technical terms. refine_query degrades to the
            # original question on any failure (RULE_SAFE_TERMINAL spirit).
            # ----------------------------------------------------------------
            optimized_query = refine_query(item.question, provider=provider)
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={
                        "tool": "refine_query",
                        "original": item.question,
                        "optimized": optimized_query,
                    },
                ),
                log_path=audit_log_path,
            )

            # ----------------------------------------------------------------
            # 2. RETRIEVE — score the OPTIMIZED query against the full corpus; apply filters
            # ----------------------------------------------------------------
            chunks = retriever.retrieve(
                optimized_query,
                topic_tags=item.topic_tags if item.topic_tags else None,
            )
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={
                        "tool": "retrieve",
                        "n_chunks": len(chunks),
                        "chunk_ids": [c.chunk_id for c in chunks],
                    },
                ),
                log_path=audit_log_path,
            )
            # Transition INTAKE → RETRIEVED
            current_state = transition(current_state, "RETRIEVED", actor="agent")
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="state_transition",
                    from_state="INTAKE",
                    to_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={"n_chunks": len(chunks)},
                ),
                log_path=audit_log_path,
            )

            # ----------------------------------------------------------------
            # 3. ASSEMBLE CONTEXT + DRAFT + GROUNDING CHECK
            # ----------------------------------------------------------------
            context_stack = assemble_context(
                item,
                chunks,
                item_number=idx,
                total_items=total,
            )
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={"tool": "assemble_context", "n_retrieval_entries": len(context_stack.retrieval)},
                ),
                log_path=audit_log_path,
            )

            raw_draft = draft_answer(context_stack, provider=provider, question=item.question)
            grounding_result = grounding_check(raw_draft, context_stack, question=item.question)
            final_draft = grounding_result.answer

            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=current_state,
                    rule=grounding_result.reason_code or RULE_AUDIT_COMPLETE,
                    detail={
                        "tool": "draft_answer",
                        "grounded": grounding_result.grounded,
                        "reason_code": grounding_result.reason_code,
                        "n_citations": len(final_draft.citations),
                    },
                ),
                log_path=audit_log_path,
            )

            # Transition RETRIEVED → DRAFTED
            current_state = transition(current_state, "DRAFTED", actor="agent")
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="state_transition",
                    from_state="RETRIEVED",
                    to_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={"grounded": grounding_result.grounded},
                ),
                log_path=audit_log_path,
            )

            # ----------------------------------------------------------------
            # 4. SCORE CONFIDENCE
            # ----------------------------------------------------------------
            confidence = score_confidence(chunks, grounding_result, item.question)
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={
                        "tool": "score_confidence",
                        "score": confidence.score,
                        "rationale": confidence.rationale,
                    },
                ),
                log_path=audit_log_path,
            )

            # Transition DRAFTED → SCORED
            current_state = transition(current_state, "SCORED", actor="agent")
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="state_transition",
                    from_state="DRAFTED",
                    to_state=current_state,
                    rule=RULE_AUDIT_COMPLETE,
                    detail={"confidence_score": confidence.score},
                ),
                log_path=audit_log_path,
            )

            # ----------------------------------------------------------------
            # 5. ROUTE FOR REVIEW
            # ----------------------------------------------------------------
            routing_decision = route_for_review(item, chunks, confidence, policy_tags)
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="tool_call",
                    from_state=current_state,
                    rule=routing_decision.rule or RULE_AUDIT_COMPLETE,
                    detail={
                        "tool": "route_for_review",
                        "should_route": routing_decision.should_route,
                        "queue": routing_decision.queue,
                        "reason_code": routing_decision.reason_code,
                    },
                ),
                log_path=audit_log_path,
            )

            if routing_decision.should_route:
                # Transition SCORED → ROUTED_FOR_REVIEW (agent is allowed)
                current_state = transition(current_state, "ROUTED_FOR_REVIEW", actor="agent")
                write_audit(
                    new_audit_event(
                        questionnaire_id=questionnaire_id,
                        item_id=item_id,
                        event="state_transition",
                        from_state="SCORED",
                        to_state=current_state,
                        rule=routing_decision.rule,
                        detail={
                            "queue": routing_decision.queue,
                            "reason_code": routing_decision.reason_code,
                        },
                    ),
                    log_path=audit_log_path,
                )
            # else: leave at SCORED — the agent NEVER self-approves (RULE_NO_SELF_APPROVE)

            routing_decisions[item_id] = routing_decision

            # ----------------------------------------------------------------
            # 6. Build the ResponseDocItem
            # ----------------------------------------------------------------
            # Collect sensitivity tags from all cited chunks
            cited_ids = {c.chunk_id for c in final_draft.citations}
            sensitivities = list({
                chunk.sensitivity for chunk in chunks if chunk.chunk_id in cited_ids
            })

            doc_item = ResponseDocItem(
                item_id=item_id,
                question=item.question,
                draft_text=final_draft.text,
                citations=list(final_draft.citations),
                confidence_score=confidence.score,
                status=current_state,
                queue=routing_decision.queue if routing_decision.should_route else None,
                sensitivities=sensitivities,
                review_approved=False,  # agent never marks this True (RULE_NO_SELF_APPROVE)
            )
            doc_items.append(doc_item)

        except Exception as exc:  # noqa: BLE001 — RULE_SAFE_TERMINAL: catch everything
            # ----------------------------------------------------------------
            # RULE_SAFE_TERMINAL: any component failure → safe terminal
            # Never an uncaught exception; never a fabricated answer.
            # ----------------------------------------------------------------
            error_msg = f"{type(exc).__name__}: {exc}"
            errors[item_id] = error_msg

            # Write the ERROR_TERMINAL audit event
            write_audit(
                new_audit_event(
                    questionnaire_id=questionnaire_id,
                    item_id=item_id,
                    event="error_terminal",
                    rule=RULE_SAFE_TERMINAL,
                    detail={
                        "reason": ERROR_TERMINAL,
                        "error": error_msg,
                    },
                ),
                log_path=audit_log_path,
            )

            # Build a safe-terminal ResponseDocItem
            doc_item = ResponseDocItem(
                item_id=item_id,
                question=getattr(item, "question", str(item_id)),
                draft_text=UNGROUNDED_PLACEHOLDER,
                citations=[],
                confidence_score=None,
                status="ROUTED_FOR_REVIEW",
                queue=None,
                sensitivities=[],
                review_approved=False,
            )
            doc_items.append(doc_item)

            # Set a no-route routing decision placeholder so the result is complete
            routing_decisions[item_id] = RoutingDecision(
                should_route=True,
                queue=None,
                reason_code=ERROR_TERMINAL,
                rule=RULE_SAFE_TERMINAL,
            )

    response_doc = ResponseDoc(
        questionnaire_id=questionnaire_id,
        generated_at=generated_at,
        items=doc_items,
    )

    return PipelineResult(
        response_doc=response_doc,
        routing=routing_decisions,
        errors=errors,
    )
