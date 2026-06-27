"""
scripts/run_demo.py — make demo (offline, mocked, no network).

Responsibility: run the full Comet pipeline on BOTH demo questionnaire cases
(case_confident + case_review) using MockLLM (deterministic, fully offline),
print a readable per-item summary, simulate the human APPROVED gate for eligible
items, and export them to local disk.

This is the mandatory offline demo (DEMO1 + DEMO2). It demonstrates:
  DEMO1 — case_confident i1/i2: confident, grounded, not routed → human-approved → exported.
           case_confident i3: high BM25 score but ROUTED_HIGH_RISK→security (defense-in-depth).
  DEMO2 — case_review:  RULE_HITM_REVIEW_TRIGGER fires → ROUTED_FOR_REVIEW with REVIEW_BANNER
           → never exported (awaits human review).

Import-safe: no side effects at import. load_env() called only inside main().
No network calls; no ANTHROPIC_API_KEY required.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `import app.*` resolves correctly
# when the script is run as `python scripts/run_demo.py` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _print_separator(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _print_item_summary(
    item_id: str,
    question: str,
    draft_text: str,
    confidence_score: float | None,
    band: str,
    routing_decision,
    status: str,
) -> None:
    """Print a readable one-item summary."""
    print(f"  Item: {item_id}")
    print(f"  Question: {question[:80]}{'...' if len(question) > 80 else ''}")
    print(f"  Status: {status}")
    if confidence_score is not None:
        print(f"  Confidence: {confidence_score:.3f}  [{band}]")
    if routing_decision.should_route:
        print(
            f"  ⚠️  ROUTED → queue={routing_decision.queue!r}  "
            f"reason={routing_decision.reason_code}"
        )
    else:
        print("  ✓  Not routed (confident draft)")
    # Show first 160 chars of draft
    preview = draft_text[:160].replace("\n", " ")
    if len(draft_text) > 160:
        preview += "..."
    print(f"  Draft preview: {preview}")


def run_case(
    questionnaire_path: Path,
    export_dir: Path,
    audit_dir: Path,
    label: str,
) -> None:
    """Load and run the pipeline on a single questionnaire case; print summary."""
    from app.kb import load_kb, load_questionnaire, load_policy_tags
    from app.retrieval import Retriever
    from app.llm import MockLLM
    from app.pipeline import run_pipeline
    from app.confidence import confidence_band
    from app.export import export_response, render_preview
    from app.audit import new_audit_event, write_audit
    from app.state import transition
    from app.config import REVIEW_BANNER, RULE_NO_SELF_APPROVE
    from app.schema import ResponseDoc

    _print_separator("=")
    print(f"DEMO CASE: {label}")
    print(f"File: {questionnaire_path.name}")
    _print_separator("=")

    questionnaire = load_questionnaire(questionnaire_path)
    qid = questionnaire["questionnaire_id"]
    audit_log_path = audit_dir / f"{qid}.jsonl"
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Build Retriever once (perf fix, D-S6)
    retriever = Retriever(load_kb())
    policy_tags = load_policy_tags()
    provider = MockLLM()

    result = run_pipeline(
        questionnaire,
        provider=provider,
        retriever=retriever,
        policy_tags=policy_tags,
        audit_log_path=audit_log_path,
    )

    print(f"\nQuestionnaire ID : {qid}")
    print(f"Items processed  : {len(result.response_doc.items)}")
    if result.errors:
        print(f"Errors           : {len(result.errors)}")
    print()

    # ---- Per-item summary ----
    for doc_item in result.response_doc.items:
        iid = doc_item.item_id
        routing = result.routing.get(iid)
        band = confidence_band(doc_item.confidence_score) if doc_item.confidence_score is not None else "n/a"

        _print_separator("-")
        _print_item_summary(
            item_id=iid,
            question=doc_item.question,
            draft_text=doc_item.draft_text,
            confidence_score=doc_item.confidence_score,
            band=band,
            routing_decision=routing,
            status=doc_item.status,
        )

        if routing and routing.should_route and routing.reason_code == "ROUTED_HIGH_RISK":
            print("  [DEFENSE-IN-DEPTH SHOWCASE: high-risk tag overrides high confidence]")

    print()

    # ---- Simulate the human gate (RULE_NO_SELF_APPROVE) ----
    # For confident non-sensitive items (SCORED, not routed, no internal/restricted),
    # simulate the human actor approving and export.

    approved_ids: list[str] = []
    updated_items = []

    for doc_item in result.response_doc.items:
        iid = doc_item.item_id
        routing = result.routing.get(iid)
        is_routed = routing and routing.should_route

        # Eligible for human approval: SCORED state + not routed + no internal/restricted sensitivity
        has_restricted_sens = bool(
            set(doc_item.sensitivities) & {"internal", "restricted"}
        )
        if doc_item.status == "SCORED" and not is_routed and not has_restricted_sens:
            # Simulate the human transition (actor="human") — the ONLY way to APPROVED
            new_status = transition(doc_item.status, "APPROVED", actor="human")
            write_audit(
                new_audit_event(
                    questionnaire_id=qid,
                    item_id=iid,
                    event="state_transition",
                    from_state=doc_item.status,
                    to_state=new_status,
                    rule=RULE_NO_SELF_APPROVE,
                    detail={"actor": "human", "action": "APPROVED"},
                ),
                log_path=audit_log_path,
            )
            # Update the doc_item in-place
            updated_item = doc_item.model_copy(update={
                "status": new_status,
                "review_approved": True,
            })
            updated_items.append(updated_item)
            approved_ids.append(iid)
        else:
            updated_items.append(doc_item)

    # Rebuild the ResponseDoc with updated statuses for export
    updated_doc = ResponseDoc(
        questionnaire_id=qid,
        generated_at=result.response_doc.generated_at,
        items=updated_items,
    )

    # ---- Export approved items ----
    if approved_ids:
        paths = export_response(updated_doc, out_dir=export_dir, log_path=audit_log_path)
        print(f"Human-approved items : {approved_ids}")
        print(f"Exported Markdown    : {paths['markdown']}")
        print(f"Exported CSV         : {paths['csv']}")
    else:
        print("No items approved for export (all pending human review).")

    # ---- Show preview with REVIEW_BANNER for routed items ----
    routed_items = [
        item for item in updated_items if item.status == "ROUTED_FOR_REVIEW"
    ]
    if routed_items:
        print()
        print("Items pending human review (NOT exported):")
        for item in routed_items:
            routing = result.routing.get(item.item_id)
            print(f"  {item.item_id} → queue={routing.queue if routing else 'unknown'}  "
                  f"reason={routing.reason_code if routing else 'unknown'}")
        print()
        preview = render_preview(updated_doc)
        if preview.startswith(REVIEW_BANNER):
            print(f"Review banner confirmed: {REVIEW_BANNER[:60]}...")

    print(f"\nAudit log: {audit_log_path}")
    print()


def main() -> None:
    """Entry point for make demo (offline, MockLLM, no network)."""
    # load_env() called here only — never at import (import-safe)
    from app.config import load_env
    load_env()

    repo_root = _repo_root()
    questionnaires_dir = repo_root / "data" / "questionnaires"
    export_dir = repo_root / "exports"
    audit_dir = repo_root / "audit"

    print()
    print("=" * 72)
    print("  COMET — RFP / Security-Questionnaire Response Agent  (make demo)")
    print("  Offline · Deterministic · MockLLM · No network")
    print("=" * 72)
    print()

    # Run DEMO1 — confident auto-draft case
    run_case(
        questionnaire_path=questionnaires_dir / "case_confident.synthetic.json",
        export_dir=export_dir,
        audit_dir=audit_dir,
        label="DEMO1 — Confident Auto-Draft",
    )

    # Run DEMO2 — human-review exception case
    run_case(
        questionnaire_path=questionnaires_dir / "case_review.synthetic.json",
        export_dir=export_dir,
        audit_dir=audit_dir,
        label="DEMO2 — Human-Review Exception",
    )

    print("=" * 72)
    print("  make demo complete — both demo cases executed offline.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
