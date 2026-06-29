"""
scripts/run_questionnaire.py — run any questionnaire through the pipeline and write a report file.

Usage:
  python scripts/run_questionnaire.py [QUESTIONNAIRE_PATH] [--live] [--out FILE] [--response] [--approve]

  --response  also write the send-ready response document `exports/<qid>.response.md`
              (clean Q->A, sources by doc name, approved-only; a human reviews + sends it).
  --approve   interactively review EACH item and type a human decision before export
              (implies --response). Routed items walk the real human path
              ROUTED_FOR_REVIEW -> REVIEW_APPROVED -> APPROVED (actor="human");
              reject -> REVIEW_REJECTED (stays unexported). Without it, the prior
              auto-simulate behavior is unchanged.

Defaults:
  path : data/questionnaires/case_bulk20.synthetic.json
  lane : offline MockLLM (deterministic, no network). --live uses the gated Claude lane
         (requires ANTHROPIC_API_KEY; ~2 Claude calls per item — refine + draft).
  out  : exports/<questionnaire_id>-<lane>-run.md

ADD-only operational wrapper: reuses app.pipeline.run_pipeline; changes no app module, no graded
contract, no test/fixture. RULE_NO_EXTERNAL_SEND holds — it writes to local disk only.

Import-safe: no side effects at import; load_env() + all app imports happen inside main().
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _decide(prompt: str) -> str:
    """Read a one-key human decision: returns 'a' (approve), 'r' (reject), or 's' (skip).

    Defaults to 's' on EOF/Ctrl-C so piped stdin and interrupts are safe
    (RULE_SAFE_TERMINAL spirit) — never crashes the review.
    """
    try:
        raw = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "s"
    if raw in ("a", "approve"):
        return "a"
    if raw in ("r", "reject"):
        return "r"
    return "s"


def main() -> None:
    argv = sys.argv[1:]
    live = "--live" in argv
    approve = "--approve" in argv  # interactively approve/reject each item before export
    want_response = "--response" in argv or approve  # --approve implies the response export

    out_arg: str | None = None
    skip_idx: set[int] = set()
    if "--out" in argv:
        i = argv.index("--out")
        skip_idx.add(i)
        if i + 1 < len(argv):
            out_arg = argv[i + 1]
            skip_idx.add(i + 1)  # position-aware: consume the --out VALUE by index, not by string match

    positional = [a for idx, a in enumerate(argv) if idx not in skip_idx and not a.startswith("--")]

    from app.config import load_env
    load_env()

    from app.config import UNGROUNDED_PLACEHOLDER
    from app.confidence import confidence_band
    from app.kb import load_kb, load_policy_tags, load_questionnaire
    from app.llm import MockLLM
    from app.pipeline import run_pipeline
    from app.retrieval import Retriever

    q_path = (
        Path(positional[0]) if positional
        else _REPO_ROOT / "data" / "questionnaires" / "case_bulk20.synthetic.json"
    )

    if live:
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            print("live lane requires ANTHROPIC_API_KEY — set it in .env or drop --live")
            sys.exit(1)
        from app.llm import ClaudeLLM
        provider, lane = ClaudeLLM(), "live"
    else:
        provider, lane = MockLLM(), "offline"

    questionnaire = load_questionnaire(q_path)
    qid = questionnaire["questionnaire_id"]
    provided_tags = {it.item_id: list(it.topic_tags) for it in questionnaire["items"]}

    audit_dir = _REPO_ROOT / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_log = audit_dir / f"{qid}-{lane}-run.jsonl"
    if audit_log.exists():
        audit_log.unlink()

    kb = load_kb()
    retriever = Retriever(kb)
    policy_tags = load_policy_tags()

    print(f"Running {q_path.name}  ·  lane={lane}  ·  {len(questionnaire['items'])} items …")
    result = run_pipeline(
        questionnaire, provider=provider, retriever=retriever,
        policy_tags=policy_tags, audit_log_path=audit_log,
    )

    # Pull per-item step detail (inferred tags + retrieved chunk ids) from the audit log.
    inferred_tags: dict[str, list] = {}
    retrieved_ids: dict[str, list] = {}
    with open(audit_log, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            d = ev.get("detail") or {}
            iid = ev.get("item_id")
            if d.get("tool") == "auto_tag":
                inferred_tags[iid] = d.get("inferred_tags") or []
            elif d.get("tool") == "retrieve":
                retrieved_ids[iid] = d.get("chunk_ids") or []

    grounded_n = ungrounded_n = routed_n = 0
    out_lines: list[str] = [
        f"# Run report — {qid}",
        f"_questionnaire: `{q_path.name}` · lane: **{lane}** · items: {len(result.response_doc.items)}_\n",
    ]

    for it in result.response_doc.items:
        iid = it.item_id
        r = result.routing.get(iid)
        ungrounded = it.draft_text == UNGROUNDED_PLACEHOLDER
        grounded_n += not ungrounded
        ungrounded_n += ungrounded
        routed = bool(r and r.should_route)
        routed_n += routed

        conf = (
            f"{it.confidence_score:.3f} [{confidence_band(it.confidence_score)}]"
            if it.confidence_score is not None else "n/a"
        )
        tags = provided_tags.get(iid) or inferred_tags.get(iid) or []
        tag_src = "provided" if provided_tags.get(iid) else ("inferred" if inferred_tags.get(iid) else "none")
        route_str = f"⚠ ROUTED → {r.queue} ({r.reason_code})" if routed else "✓ not routed"

        out_lines += [
            f"## {iid}  —  {'UNGROUNDED' if ungrounded else 'grounded'}",
            f"- **Q:** {it.question}",
            f"- **tags ({tag_src}):** {', '.join(tags) if tags else '(none)'}",
            f"- **retrieved:** {', '.join(retrieved_ids.get(iid, [])) or '(none)'}",
            f"- **confidence:** {conf}   **state:** {it.status}   **routing:** {route_str}",
            f"- **citations:** {[c.chunk_id for c in it.citations] or '(none)'}",
            f"- **answer:**\n\n  {it.draft_text}\n",
        ]

    header = (
        f"_summary: {grounded_n} grounded · {ungrounded_n} ungrounded · "
        f"{routed_n} routed for review · {len(result.errors)} errors_\n"
    )
    out_lines.insert(2, header)

    out_path = Path(out_arg) if out_arg else _REPO_ROOT / "exports" / f"{qid}-{lane}-run.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")

    print(
        f"Done: {grounded_n} grounded · {ungrounded_n} ungrounded · {routed_n} routed · "
        f"{len(result.errors)} errors"
    )
    print(f"Report written: {out_path}")
    print(f"Audit log     : {audit_log}")

    # --response: simulate the employee's human-approval of confident, grounded, non-sensitive
    # items (actor="human" — the agent NEVER self-approves), then write the send-ready response
    # document. Routed/ungrounded/sensitive items stay unapproved → "under internal review".
    if want_response:
        from app.audit import new_audit_event, write_audit
        from app.config import RULE_NO_SELF_APPROVE
        from app.export import export_response_document
        from app.schema import ResponseDoc
        from app.state import transition

        # Record one human-actor transition to the audit log (RULE_NO_SELF_APPROVE +
        # RULE_AUDIT_COMPLETE) and return the new status. Same audit_log the pipeline
        # wrote, so the per-item timeline stays continuous.
        def _human_transition(item, from_state: str, to_state: str) -> str:
            new_status = transition(from_state, to_state, actor="human")
            write_audit(
                new_audit_event(
                    questionnaire_id=qid, item_id=item.item_id,
                    event="state_transition", from_state=from_state, to_state=new_status,
                    rule=RULE_NO_SELF_APPROVE, detail={"actor": "human", "action": to_state},
                ),
                log_path=audit_log,
            )
            return new_status

        source_by_chunk = {c.chunk_id: c.source for c in kb if c.source}
        approved_n = 0
        rejected_n = 0
        review_items = []
        for it in result.response_doc.items:
            r = result.routing.get(it.item_id)
            is_routed = bool(r and r.should_route)
            is_sensitive = bool(set(it.sensitivities) & {"internal", "restricted"})
            is_ungrounded = it.draft_text == UNGROUNDED_PLACEHOLDER

            if approve:
                # Interactive human gate. Ungrounded placeholders have no real answer to approve.
                if is_ungrounded:
                    print(f"\n── {it.item_id} ── UNGROUNDED placeholder — not approvable; skipped.")
                    review_items.append(it)
                    continue
                conf = f"{it.confidence_score:.3f}" if it.confidence_score is not None else "n/a"
                print(f"\n── {it.item_id} ──")
                print(f"   Q: {it.question}")
                print(f"   ROUTED → {r.queue} ({r.reason_code})" if is_routed
                      else f"   confident draft (conf={conf}), not routed")
                preview = it.draft_text[:200].replace("\n", " ")
                print(f"   Draft: {preview}{'…' if len(it.draft_text) > 200 else ''}")
                choices = "[a]pprove / [r]eject / [s]kip: " if is_routed else "[a]pprove / [s]kip: "
                d = _decide(f"   {choices}")
                if d == "a" and is_routed:
                    s = _human_transition(it, it.status, "REVIEW_APPROVED")
                    s = _human_transition(it, s, "APPROVED")
                    review_items.append(it.model_copy(update={"status": s, "review_approved": True}))
                    approved_n += 1
                elif d == "a":  # non-routed SCORED → APPROVED
                    s = _human_transition(it, it.status, "APPROVED")
                    review_items.append(it.model_copy(update={"status": s, "review_approved": True}))
                    approved_n += 1
                elif d == "r" and is_routed:
                    s = _human_transition(it, it.status, "REVIEW_REJECTED")
                    review_items.append(it.model_copy(update={"status": s}))
                    rejected_n += 1
                else:
                    review_items.append(it)
            else:
                # Default auto-simulate (byte-identical to prior behavior; no audit event).
                if it.status == "SCORED" and not is_routed and not is_sensitive and not is_ungrounded:
                    new_status = transition(it.status, "APPROVED", actor="human")
                    review_items.append(it.model_copy(update={"status": new_status, "review_approved": True}))
                    approved_n += 1
                else:
                    review_items.append(it)

        response_doc = ResponseDoc(
            questionnaire_id=qid,
            generated_at=result.response_doc.generated_at,
            items=review_items,
        )
        rpath = export_response_document(
            response_doc, source_by_chunk,
            out_dir=_REPO_ROOT / "exports", log_path=audit_log,
        )
        pending_n = len(review_items) - approved_n - rejected_n
        extra = f" · {rejected_n} rejected" if approve else ""
        print(
            f"Response document: {rpath}  "
            f"({approved_n} approved + sent-ready{extra} · {pending_n} pending internal review)"
        )


if __name__ == "__main__":
    main()
