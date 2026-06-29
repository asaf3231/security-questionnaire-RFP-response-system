"""
scripts/run_live_draft.py — make demo-live (gated live Claude draft).

Responsibility: run the Comet pipeline on the confident demo case using the
ClaudeLLM provider (the real Claude API), then run an INTERACTIVE human-review
gate — a person types approve/reject per item; approved items are exported, a
rejected item's answer becomes "answer rejected". Requires ANTHROPIC_API_KEY to
be set. If the key is absent, prints a clear message and exits 0 (clean skip).

This is the ONLY path in the system that makes a Claude API call.
It still writes to local disk only — no external send (RULE_NO_EXTERNAL_SEND).
Approval is a human action only (actor="human"); the agent never self-approves
(RULE_NO_SELF_APPROVE). Decisions read from stdin; there is no skip — EOF/Ctrl-C
aborts the review and leaves remaining items unreviewed.

Import-safe: no side effects at import. load_env() + API key check inside main() only.
"""

from __future__ import annotations

import json
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


def _decide(prompt: str) -> str:
    """Read a human decision: 'a' (approve) or 'r' (reject). Re-prompts on anything else.

    There is no skip option. Returns 'q' (abort) only on EOF/Ctrl-C so exhausted or
    piped stdin can't loop forever (RULE_SAFE_TERMINAL spirit); the caller then leaves
    that item and the rest unreviewed.
    """
    while True:
        try:
            raw = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
        if raw in ("a", "approve"):
            return "a"
        if raw in ("r", "reject"):
            return "r"
        print("  please type 'a' (approve) or 'r' (reject)")


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
    from app.export import export_response, export_response_document
    from app.audit import new_audit_event, write_audit
    from app.state import transition
    from app.config import RULE_NO_SELF_APPROVE, UNGROUNDED_PLACEHOLDER
    from app.schema import ResponseDoc

    repo_root = _repo_root()
    questionnaire_path = repo_root / "data" / "questionnaires" / "case_demo_live.synthetic.json"
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

    kb = load_kb()
    retriever = Retriever(kb)
    source_by_chunk = {c.chunk_id: c.source for c in kb if c.source}
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

    # Stage 10: surface QUERY_REFINEMENT (raw → optimized) from the audit trail for the demo.
    # Read from the audit log rather than re-calling the model (no redundant API call).
    refine_by_item: dict[str, dict] = {}
    try:
        with open(audit_log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                detail = ev.get("detail") or {}
                if detail.get("tool") == "refine_query":
                    refine_by_item[ev.get("item_id")] = detail
    except (OSError, ValueError):
        refine_by_item = {}

    # Per-item summary
    for doc_item in result.response_doc.items:
        iid = doc_item.item_id
        routing = result.routing.get(iid)
        band = confidence_band(doc_item.confidence_score) if doc_item.confidence_score is not None else "n/a"
        conf_str = f"{doc_item.confidence_score:.3f}" if doc_item.confidence_score is not None else "n/a"
        print()
        print(f"  {iid}  [{doc_item.status}]  confidence={conf_str}  band={band}")
        print(f"  Question: {doc_item.question[:80]}{'...' if len(doc_item.question) > 80 else ''}")
        ref = refine_by_item.get(iid)
        if ref and ref.get("optimized") != ref.get("original"):
            opt = ref.get("optimized", "")
            print(f"  Refined query → {opt[:90]}{'...' if len(opt) > 90 else ''}")
        if routing and routing.should_route:
            print(f"  ROUTED → queue={routing.queue}  reason={routing.reason_code}")
        else:
            print("  Not routed (confident draft — awaits human APPROVED)")
        preview = doc_item.draft_text[:200].replace("\n", " ")
        if len(doc_item.draft_text) > 200:
            preview += "..."
        print(f"  Draft: {preview}")

    # Stage 10: confirm the <thinking> scaffold never leaked into a drafted answer.
    leaked = [d.item_id for d in result.response_doc.items if "<thinking>" in d.draft_text]
    print()
    print(f"<thinking> stripped from all drafts: {not leaked}" + (f"  LEAK={leaked}" if leaked else ""))

    # Interactive human-review gate (RULE_NO_SELF_APPROVE — actor="human" only).
    # A person types approve/reject/skip per item; approved items are exported.
    def _human_transition(item, from_state: str, to_state: str) -> str:
        """Record one human-actor transition to the audit log and return the new status."""
        new_status = transition(from_state, to_state, actor="human")
        write_audit(
            new_audit_event(
                questionnaire_id=qid,
                item_id=item.item_id,
                event="state_transition",
                from_state=from_state,
                to_state=new_status,
                rule=RULE_NO_SELF_APPROVE,
                detail={"actor": "human", "action": to_state},
            ),
            log_path=audit_log_path,
        )
        return new_status

    print()
    print("─" * 72)
    print("  HUMAN REVIEW — approve/reject each item (you, actor=human)")
    print("─" * 72)

    updated_items = []
    approved_ids = []
    rejected_ids = []
    aborted = False

    for doc_item in result.response_doc.items:
        iid = doc_item.item_id
        routing = result.routing.get(iid)
        is_routed = bool(routing and routing.should_route)
        is_ungrounded = doc_item.draft_text == UNGROUNDED_PLACEHOLDER

        # Once aborted (EOF/Ctrl-C), leave every remaining item unreviewed.
        if aborted:
            updated_items.append(doc_item)
            continue

        # Ungrounded placeholders have no real answer to approve.
        if is_ungrounded:
            print(f"\n  {iid}: UNGROUNDED placeholder — not approvable; left unreviewed.")
            updated_items.append(doc_item)
            continue

        conf_str = f"{doc_item.confidence_score:.3f}" if doc_item.confidence_score is not None else "n/a"
        print(f"\n  {iid}  (confidence={conf_str})")
        if is_routed:
            print(f"  ROUTED → queue={routing.queue}  reason={routing.reason_code}")
        else:
            print("  Not routed (confident draft)")
        choice = _decide("  [a]pprove / [r]eject: ")

        if choice == "q":  # EOF/Ctrl-C — abort; leave this and the rest unreviewed
            aborted = True
            updated_items.append(doc_item)
            continue
        if choice == "a" and is_routed:
            s = _human_transition(doc_item, doc_item.status, "REVIEW_APPROVED")
            s = _human_transition(doc_item, s, "APPROVED")
            updated_items.append(doc_item.model_copy(update={"status": s, "review_approved": True}))
            approved_ids.append(iid)
        elif choice == "a":  # non-routed SCORED → APPROVED
            s = _human_transition(doc_item, doc_item.status, "APPROVED")
            updated_items.append(doc_item.model_copy(update={"status": s, "review_approved": True}))
            approved_ids.append(iid)
        elif is_routed:  # reject a routed item → REVIEW_REJECTED
            s = _human_transition(doc_item, doc_item.status, "REVIEW_REJECTED")
            updated_items.append(doc_item.model_copy(update={"status": s}))
            rejected_ids.append(iid)
        else:  # reject a confident non-routed item: human flags then rejects (SCORED→ROUTED_FOR_REVIEW→REVIEW_REJECTED)
            s = _human_transition(doc_item, doc_item.status, "ROUTED_FOR_REVIEW")
            s = _human_transition(doc_item, s, "REVIEW_REJECTED")
            updated_items.append(doc_item.model_copy(update={"status": s}))
            rejected_ids.append(iid)

    updated_doc = ResponseDoc(
        questionnaire_id=qid,
        generated_at=result.response_doc.generated_at,
        items=updated_items,
    )

    print()
    print(f"Human-approved: {approved_ids or '(none)'}")
    if rejected_ids:
        print(f"Human-rejected: {rejected_ids}")

    # Approved-only artifacts (audit/governance): .md + .csv, APPROVED items only.
    if approved_ids:
        paths = export_response(updated_doc, out_dir=export_dir, log_path=audit_log_path)
        print(f"Exported (approved-only) Markdown: {paths['markdown']}")
        print(f"Exported (approved-only) CSV     : {paths['csv']}")
    else:
        print("No items approved → approved-only export is empty.")

    # Send-ready response document — ALL questions: approved show the answer,
    # rejected show "answer rejected", anything else "under internal review".
    response_path = export_response_document(
        updated_doc, source_by_chunk, out_dir=export_dir, log_path=audit_log_path
    )
    print(f"Response document (all questions): {response_path}")

    print(f"\nAudit log: {audit_log_path}")
    print()
    print("=" * 72)
    print("  make demo-live complete.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
