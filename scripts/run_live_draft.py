"""
scripts/run_live_draft.py — make demo-live (gated live Claude draft).

Responsibility: run the Comet pipeline on the confident demo case using the
ClaudeLLM provider (the real Claude API). Requires ANTHROPIC_API_KEY to be set.
If the key is absent, prints a clear message and exits 0 (clean skip, not failure).

This is the ONLY path in the system that makes a Claude API call.
It still writes to local disk only — no external send (RULE_NO_EXTERNAL_SEND).

Import-safe: no side effects at import. load_env() + API key check inside main() only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `import app.*` resolves correctly
# when the script is run as `python scripts/run_live_draft.py` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> None:
    """Entry point for make demo-live (gated; requires ANTHROPIC_API_KEY)."""
    # load_env() called here only — never at import (import-safe)
    from app.config import load_env
    load_env()

    # Gating check — clean skip if no key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print()
        print("live lane requires ANTHROPIC_API_KEY — skipping")
        print("(set ANTHROPIC_API_KEY in .env and re-run make demo-live)")
        print()
        sys.exit(0)

    from app.kb import load_kb, load_questionnaire, load_policy_tags
    from app.retrieval import Retriever
    from app.llm import ClaudeLLM
    from app.pipeline import run_pipeline
    from app.confidence import confidence_band
    from app.export import export_response
    from app.audit import new_audit_event, write_audit
    from app.state import transition
    from app.config import RULE_NO_SELF_APPROVE
    from app.schema import ResponseDoc

    repo_root = _repo_root()
    questionnaire_path = repo_root / "data" / "questionnaires" / "case_confident.synthetic.json"
    export_dir = repo_root / "exports"
    audit_dir = repo_root / "audit"

    print()
    print("=" * 72)
    print("  COMET — RFP / Security-Questionnaire Response Agent  (make demo-live)")
    print("  Live Claude API · Gated · No external send")
    print("=" * 72)
    print()

    questionnaire = load_questionnaire(questionnaire_path)
    qid = questionnaire["questionnaire_id"]
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_log_path = audit_dir / f"{qid}-live.jsonl"

    retriever = Retriever(load_kb())
    policy_tags = load_policy_tags()
    provider = ClaudeLLM()  # gated live lane — uses the real Claude API

    print(f"Questionnaire: {questionnaire_path.name}")
    print(f"Provider     : ClaudeLLM (model={__import__('app.config', fromlist=['DRAFT_MODEL']).DRAFT_MODEL})")
    print()

    result = run_pipeline(
        questionnaire,
        provider=provider,
        retriever=retriever,
        policy_tags=policy_tags,
        audit_log_path=audit_log_path,
    )

    print(f"Items processed: {len(result.response_doc.items)}")
    if result.errors:
        print(f"Errors         : {len(result.errors)}")

    # Per-item summary
    for doc_item in result.response_doc.items:
        iid = doc_item.item_id
        routing = result.routing.get(iid)
        band = confidence_band(doc_item.confidence_score) if doc_item.confidence_score is not None else "n/a"
        print()
        print(f"  {iid}  [{doc_item.status}]  confidence={doc_item.confidence_score:.3f}  band={band}")
        print(f"  Question: {doc_item.question[:80]}{'...' if len(doc_item.question) > 80 else ''}")
        if routing and routing.should_route:
            print(f"  ROUTED → queue={routing.queue}  reason={routing.reason_code}")
        else:
            print("  Not routed (confident draft — awaits human APPROVED)")
        preview = doc_item.draft_text[:200].replace("\n", " ")
        if len(doc_item.draft_text) > 200:
            preview += "..."
        print(f"  Draft: {preview}")

    # Simulate human approval for non-routed, non-sensitive items and export
    updated_items = []
    approved_ids = []

    for doc_item in result.response_doc.items:
        iid = doc_item.item_id
        routing = result.routing.get(iid)
        is_routed = routing and routing.should_route
        has_restricted_sens = bool(set(doc_item.sensitivities) & {"internal", "restricted"})

        if doc_item.status == "SCORED" and not is_routed and not has_restricted_sens:
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
            updated_items.append(doc_item.model_copy(update={"status": new_status, "review_approved": True}))
            approved_ids.append(iid)
        else:
            updated_items.append(doc_item)

    updated_doc = ResponseDoc(
        questionnaire_id=qid,
        generated_at=result.response_doc.generated_at,
        items=updated_items,
    )

    if approved_ids:
        paths = export_response(updated_doc, out_dir=export_dir, log_path=audit_log_path)
        print()
        print(f"Human-approved: {approved_ids}")
        print(f"Exported Markdown: {paths['markdown']}")
        print(f"Exported CSV     : {paths['csv']}")
    else:
        print("\nNo items approved for export.")

    print(f"\nAudit log: {audit_log_path}")
    print()
    print("=" * 72)
    print("  make demo-live complete.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
