"""
app/schema.py — Pydantic models for all data structures in Comet.

Responsibility: define and validate all data structures used across the pipeline.
No side effects at import — no data read, no client, no network.

Models: QuestionnaireItem, RetrievedChunk, ContextStack, Citation, DraftAnswer,
        ConfidenceResult, RoutingDecision, AuditEvent, ResponseDoc.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class QuestionnaireItem(BaseModel):
    """A single question from an incoming questionnaire."""

    item_id: str
    question: str
    topic_tags: list[str] = Field(default_factory=list)

    @field_validator("item_id", "question")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("item_id and question must be non-empty strings")
        return v


class RetrievedChunk(BaseModel):
    """A single KB chunk returned by the retrieval layer."""

    chunk_id: str
    question: Optional[str] = None
    answer: str
    source: Optional[str] = None
    sensitivity: str  # ∈ SENSITIVITY_TAGS
    topic_tags: list[str] = Field(default_factory=list)
    approved: bool = True
    bm25_score: float = 0.0  # set by retrieval; 0.0 as default for KB load stage


# ---------------------------------------------------------------------------
# Context Stack — the 4-layer "backpack" (Stage 3)
# ---------------------------------------------------------------------------

class ContextStack(BaseModel):
    """The 4-layer context passed to the LLM for a single questionnaire item.

    Layers (in order):
      instruction — explicit RFP/questionnaire handling rules and persona
      retrieval   — ONLY the top-K retrieved chunk texts (no other KB content)
      constraint  — active hard boundaries (e.g. sensitivity / governance rules)
      state       — position in the questionnaire + item's current state
    """

    instruction: str
    retrieval: list[str]  # only retrieved chunk texts; nothing else reaches the model
    constraint: str
    state: str


# ---------------------------------------------------------------------------
# Draft + citations
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    """A reference to a retrieved chunk cited by a drafted answer."""

    chunk_id: str
    source: Optional[str] = None


class DraftAnswer(BaseModel):
    """The output of draft_answer(): a text draft plus its cited sources."""

    text: str
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def text_must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DraftAnswer.text must be a non-empty string")
        return v


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class ConfidenceResult(BaseModel):
    """Hybrid confidence: deterministic numeric score + optional LLM rationale string."""

    score: float = Field(ge=0.0, le=1.0)
    rationale: str = ""  # explanatory only; does NOT affect the score or routing


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    """The output of route_for_review(): whether to route + destination queue."""

    should_route: bool
    queue: Optional[str] = None          # one of REVIEWER_QUEUES or None
    reason_code: Optional[str] = None    # e.g. ROUTED_HIGH_RISK, ROUTED_AMBIGUOUS, ROUTED_LOW_CONFIDENCE
    rule: Optional[str] = None           # the RULE_* identifier that fired


# ---------------------------------------------------------------------------
# Audit event
# ---------------------------------------------------------------------------

class AuditEvent(BaseModel):
    """A single append-only entry in the JSONL audit log.

    Every state transition and every tool call emits exactly one AuditEvent
    (RULE_AUDIT_COMPLETE). Audit records must never contain secrets or real PII
    (RULE_NO_SECRET / RULE_NO_REAL_PII).
    """

    timestamp: str                        # ISO-8601; set by audit.py
    questionnaire_id: str
    item_id: str
    event: str                            # e.g. "state_transition", "tool_call", "rule_fired"
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    rule: Optional[str] = None            # RULE_* reason-code if one fired
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("questionnaire_id", "item_id", "event")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("questionnaire_id, item_id, and event must be non-empty")
        return v


# ---------------------------------------------------------------------------
# Response document
# ---------------------------------------------------------------------------

class ResponseDocItem(BaseModel):
    """A single item's entry in the exported response document."""

    item_id: str
    question: str
    draft_text: str
    citations: list[Citation] = Field(default_factory=list)
    confidence_score: Optional[float] = None
    status: str                           # the item's current ITEM_STATE
    queue: Optional[str] = None           # reviewer queue if routed
    # Stage 5 additive fields (D-S5): used by the sensitivity gate in app/export.py
    sensitivities: list[str] = Field(default_factory=list)  # sensitivity tags of cited chunks
    review_approved: bool = False          # True iff item passed the REVIEW_APPROVED human gate


class ResponseDoc(BaseModel):
    """The exported response document for a completed questionnaire run."""

    questionnaire_id: str
    generated_at: str                     # ISO-8601 timestamp
    items: list[ResponseDocItem] = Field(default_factory=list)
