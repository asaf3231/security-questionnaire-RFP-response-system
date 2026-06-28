"""
tests/test_response_document.py — the send-ready response document renderer.

ADD-only. Covers app.export.render_response_document:
  - APPROVED items show clean prose with [chunk_id] markers + any 'Sources:' line stripped,
    plus a human-readable "Source: <doc name>" line;
  - not-yet-approved items show "under internal review" (NO answer text leaked);
  - REVIEW_BANNER prepended whenever any item is unapproved;
  - NO internal machinery (confidence / queue / status / [kb-id]) ever appears in the output.
"""

from __future__ import annotations

from app.config import REVIEW_BANNER
from app.export import render_response_document
from app.schema import Citation, ResponseDoc, ResponseDocItem


def _item(item_id, question, draft, *, status, citations=(), sensitivities=(), queue=None):
    return ResponseDocItem(
        item_id=item_id,
        question=question,
        draft_text=draft,
        citations=[Citation(chunk_id=c) for c in citations],
        confidence_score=0.812,
        status=status,
        queue=queue,
        sensitivities=list(sensitivities),
        review_approved=(status == "APPROVED"),
    )


_SRC = {"kb-001": "security-whitepaper-v3.pdf", "kb-008": "access-control-policy-v3.pdf"}


def test_approved_item_clean_prose_and_source_name():
    doc = ResponseDoc(questionnaire_id="q-x", generated_at="2026-06-28T12:00:00Z", items=[
        _item("q-x-i1", "Do you encrypt at rest?",
              "Yes, data is encrypted at rest using AES-256 [kb-001]. Access is logged [kb-008].\nSources: [kb-001], [kb-008]",
              status="APPROVED", citations=("kb-001", "kb-008")),
    ])
    out = render_response_document(doc, _SRC)
    # citations + Sources line stripped → clean prose
    assert "[kb-001]" not in out and "[kb-008]" not in out
    assert "Sources:" not in out
    assert "Yes, data is encrypted at rest using AES-256." in out
    assert "Access is logged." in out
    # human-readable source names present
    assert "security-whitepaper-v3.pdf" in out
    assert "access-control-policy-v3.pdf" in out


def test_no_internal_machinery_leaks():
    doc = ResponseDoc(questionnaire_id="q-x", generated_at="2026-06-28T12:00:00Z", items=[
        _item("q-x-i1", "Q?", "Answer [kb-001].\nSources: [kb-001]",
              status="APPROVED", citations=("kb-001",)),
    ])
    out = render_response_document(doc, _SRC)
    for forbidden in ("0.812", "Confidence", "queue", "Reviewer", "SCORED", "APPROVED", "kb-001"):
        assert forbidden not in out, f"internal field leaked: {forbidden!r}"


def test_unapproved_item_shows_pending_no_answer():
    doc = ResponseDoc(questionnaire_id="q-x", generated_at="2026-06-28T12:00:00Z", items=[
        _item("q-x-i1", "Do you carry insurance?",
              "Secret internal draft answer [kb-011].", status="ROUTED_FOR_REVIEW",
              citations=("kb-011",), sensitivities=("restricted",), queue="legal"),
    ])
    out = render_response_document(doc, _SRC)
    assert "under internal review" in out.lower()
    assert "Secret internal draft answer" not in out  # unapproved answer text never leaks
    assert "legal" not in out


def test_banner_prepended_when_any_unapproved():
    doc = ResponseDoc(questionnaire_id="q-x", generated_at="2026-06-28T12:00:00Z", items=[
        _item("q-x-i1", "Q1", "A1 [kb-001].\nSources: [kb-001]", status="APPROVED", citations=("kb-001",)),
        _item("q-x-i2", "Q2", "draft", status="ROUTED_FOR_REVIEW"),
    ])
    out = render_response_document(doc, _SRC)
    assert out.startswith(REVIEW_BANNER)


def test_no_banner_when_all_approved():
    doc = ResponseDoc(questionnaire_id="q-x", generated_at="2026-06-28T12:00:00Z", items=[
        _item("q-x-i1", "Q1", "A1 [kb-001].\nSources: [kb-001]", status="APPROVED", citations=("kb-001",)),
    ])
    out = render_response_document(doc, _SRC)
    assert not out.startswith(REVIEW_BANNER)
