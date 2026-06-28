"""
scripts/run_live_review.py — ADD-only LIVE review export (reviewer artifact).

Responsibility: drive the REAL production gates (retrieve → assemble_context →
draft → grounding_check → score_confidence → route_for_review) over the breadth of
inputs (eval gold + demo + red-team matrix) using the live ClaudeLLM, and write a
REVIEWER-FRIENDLY file that, for every input, records:
  - the INPUT  (id, source, question, topic_tags) + the GOLD expectation (where known),
  - the retrieved chunk_ids,
  - the RAW LLM ANSWER (the exact text Claude wrote, before the grounding gate),
  - the GATE VERDICTS: grounded? + which of the 4 grounding conditions tripped + the
    computed coverage / question-coverage numbers, confidence score + band, routing,
  - whether the live result MATCHED the gold (so a human can judge if the system works).

Two files are written (both key-redacted, both ADD-only, both local):
  - redteam/LIVE_REVIEW_<N>.md     (human-readable, one section per input)
  - redteam/live_review_<N>.jsonl  (machine-readable, one JSON object per input)

Governance:
  * ADD-only NON-graded operational script (not under tests/); changes no graded contract.
  * RULE_NO_SECRET — the key is read from the untracked .env and NEVER printed/written;
    every emitted string passes through _redact().
  * RULE_NO_EXTERNAL_SEND — only the gated Claude API is called; output is local disk.
  * RULE_SAFE_TERMINAL (spirit) — per-input failures are caught + recorded, never crash.

Import-safe: no work at import; everything happens inside main().

Usage:
    python scripts/run_live_review.py [--limit N]   # default N=50
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Allowlisted-stdlib-only flag parse (no argparse — ENV2 import scanner).
def _parse_limit(argv: list[str], default: int = 50) -> int:
    for i, a in enumerate(argv):
        if a == "--limit" and i + 1 < len(argv):
            return int(argv[i + 1])
        if a.startswith("--limit="):
            return int(a.split("=", 1)[1])
    return default


_SK_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")
_KEYWORD_RE = re.compile(r"(ANTHROPIC_API_KEY)\s*=\s*\S+")


def _redact(text: str) -> str:
    """Scrub any Anthropic secret token (RULE_NO_SECRET defence-in-depth)."""
    if not isinstance(text, str):
        text = str(text)
    text = _SK_RE.sub("[REDACTED-SECRET]", text)
    text = _KEYWORD_RE.sub(r"\1=[REDACTED-SECRET]", text)
    return text


_MAX_LIVE_QUESTION_CHARS = 2000


def _gather_inputs() -> list[dict]:
    """eval gold + demo questionnaires + red-team matrix → unified input records."""
    from app.kb import load_questionnaire

    records: list[dict] = []

    eval_path = _REPO_ROOT / "fixtures" / "eval" / "eval_cases.synthetic.json"
    for c in json.loads(eval_path.read_text(encoding="utf-8")):
        records.append({
            "id": c["item_id"], "source": "eval", "question": c["question"],
            "topic_tags": c.get("topic_tags", []),
            "exp_grounded": c.get("expected_grounded"), "exp_routed": c.get("expected_routed"),
            "exp_queue": c.get("expected_queue"), "exp_reason": c.get("expected_reason"),
        })

    for fname in ("case_confident.synthetic.json", "case_review.synthetic.json"):
        qpath = _REPO_ROOT / "data" / "questionnaires" / fname
        if qpath.exists():
            for item in load_questionnaire(qpath)["items"]:
                records.append({
                    "id": item.item_id, "source": "demo", "question": item.question,
                    "topic_tags": item.topic_tags,
                    "exp_grounded": None, "exp_routed": None, "exp_queue": None, "exp_reason": None,
                })

    mpath = _REPO_ROOT / "tests" / "redteam" / "redteam_inputs.synthetic.json"
    if mpath.exists():
        for r in json.loads(mpath.read_text(encoding="utf-8")):
            if r.get("expect_construct_error"):
                continue  # empty/whitespace cases are validation, not a gate test
            q = r["question"] * 4 if r.get("inflate_to_bytes") else r["question"]
            exp = r["expected"]
            exp_routed = exp.get("should_route")
            if "route_reason" in exp:
                exp_routed = True
            exp_grounded = (not exp["placeholder"]) if "placeholder" in exp else None
            records.append({
                "id": r["id"], "source": f"matrix:{r['spectrum']}", "question": q,
                "topic_tags": r["topic_tags"],
                "exp_grounded": exp_grounded, "exp_routed": exp_routed,
                "exp_queue": exp.get("queue"), "exp_reason": exp.get("route_reason"),
            })

    return records


def _grounding_diag(draft, ctx, question: str) -> dict:
    """Replicate grounding_check's 4 conditions for transparency: which one tripped + the numbers."""
    from app.config import (
        GROUNDING_COVERAGE_MIN,
        GROUNDING_MIN_CITATIONS,
        GROUNDING_QUESTION_COVERAGE_MIN,
        UNGROUNDED_PLACEHOLDER,
    )
    from app.draft import (
        _cited_chunks_text,
        _compute_coverage,
        _retrieval_chunk_ids,
        _significant_tokens,
    )

    n = len(draft.citations)
    known = _retrieval_chunk_ids(ctx)
    fabricated = [c.chunk_id for c in draft.citations if c.chunk_id not in known]
    diag: dict = {
        "n_citations": n, "min_citations": GROUNDING_MIN_CITATIONS,
        "fabricated_citations": fabricated, "coverage": None, "coverage_min": GROUNDING_COVERAGE_MIN,
        "question_coverage": None, "question_coverage_min": GROUNDING_QUESTION_COVERAGE_MIN,
        "failing_condition": None,
    }
    if n < GROUNDING_MIN_CITATIONS:
        diag["failing_condition"] = "1_too_few_citations"
        return diag
    if fabricated:
        diag["failing_condition"] = "2_fabricated_citation"
        return diag
    if draft.text == UNGROUNDED_PLACEHOLDER:
        diag["failing_condition"] = "placeholder_text"
        return diag
    cited_text = _cited_chunks_text(draft.citations, ctx)
    cov = _compute_coverage(draft.text, cited_text)
    diag["coverage"] = round(cov, 4)
    if cov < GROUNDING_COVERAGE_MIN:
        diag["failing_condition"] = "3_low_content_coverage"
    qtok = _significant_tokens(question)
    qcov = (len(qtok & _significant_tokens(cited_text)) / len(qtok)) if qtok else 1.0
    diag["question_coverage"] = round(qcov, 4)
    if diag["failing_condition"] is None and qcov < GROUNDING_QUESTION_COVERAGE_MIN:
        diag["failing_condition"] = "4_low_question_coverage"
    return diag


def _preflight(provider) -> tuple[bool, str]:
    from app.config import DRAFT_MODEL, _get_claude
    try:
        client = _get_claude()
        resp = client.messages.create(
            model=DRAFT_MODEL, max_tokens=8, temperature=0.0,
            messages=[{"role": "user", "content": "ping"}],
        )
        txt = "".join(getattr(b, "text", "") for b in resp.content).strip()
        return True, _redact(f"live OK (model={DRAFT_MODEL}, replied {len(txt)} chars)")
    except Exception as exc:  # noqa: BLE001
        return False, _redact(f"{type(exc).__name__}: {exc}")


def main() -> None:
    limit = _parse_limit(sys.argv[1:], default=50)

    from app.config import DRAFT_MODEL, load_env
    load_env()

    import os
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("\nlive lane requires ANTHROPIC_API_KEY in .env — nothing to run.\n")
        sys.exit(0)

    from app.confidence import confidence_band, score_confidence
    from app.context_stack import assemble_context
    from app.draft import grounding_check
    from app.kb import load_kb, load_policy_tags
    from app.llm import ClaudeLLM, MockLLM
    from app.retrieval import Retriever
    from app.routing import route_for_review
    from app.schema import ConfidenceResult, QuestionnaireItem

    print("=" * 78)
    print("  COMET — LIVE REVIEW EXPORT  (real ClaudeLLM through the production gates)")
    print(f"  model={DRAFT_MODEL}  ·  limit={limit}  ·  key source=.env (redacted)")
    print("=" * 78)

    live = ClaudeLLM()
    mock = MockLLM()

    ok, msg = _preflight(live)
    print(f"\n[pre-flight] {msg}")
    if not ok:
        print("\n[pre-flight] live lane NOT reachable — aborting before any breadth calls.\n")
        sys.exit(1)

    retriever = Retriever(load_kb())
    policy = load_policy_tags()
    records = _gather_inputs()[:limit]
    total = len(records)
    print(f"[inputs] {total} inputs (eval + demo + red-team matrix), capped at --limit={limit}\n")

    results: list[dict] = []
    errors = 0
    for i, rec in enumerate(records, start=1):
        question = rec["question"][:_MAX_LIVE_QUESTION_CHARS]
        try:
            item = QuestionnaireItem(item_id=rec["id"], question=question, topic_tags=rec["topic_tags"])
            chunks = retriever.retrieve(question, topic_tags=item.topic_tags or None)
            ctx = assemble_context(item, chunks, item_number=i, total_items=total)

            live_draft = live.draft(ctx)                                   # RAW prose
            grounding = grounding_check(live_draft, ctx, question=question)
            diag = _grounding_diag(live_draft, ctx, question)
            conf = score_confidence(chunks, grounding, question)
            band = confidence_band(conf.score)
            route = route_for_review(item, chunks, ConfidenceResult(score=conf.score), policy)

            # Offline mock for determinism comparison (free, no API).
            mock_draft = mock.draft(ctx)
            mock_grounding = grounding_check(mock_draft, ctx, question=question)
        except Exception as exc:  # noqa: BLE001 — never crash the harness
            errors += 1
            print(f"  [{i:>3}/{total}] {rec['id']:<16} ERROR {_redact(type(exc).__name__)}")
            results.append({**rec, "error": _redact(f"{type(exc).__name__}: {exc}")})
            continue

        gold_grounded_match = (
            None if rec["exp_grounded"] is None else (grounding.grounded == rec["exp_grounded"])
        )
        gold_routed_match = (
            None if rec["exp_routed"] is None else (route.should_route == rec["exp_routed"])
        )

        results.append({
            **rec,
            "retrieved_chunk_ids": [c.chunk_id for c in chunks],
            "retrieved_sensitivities": [c.sensitivity for c in chunks],
            "llm_answer_raw": _redact(live_draft.text),
            "llm_citations": [c.chunk_id for c in live_draft.citations],
            "grounded": grounding.grounded,
            "grounding_reason_code": grounding.reason_code,
            "grounding_diag": diag,
            "confidence_score": round(conf.score, 4),
            "confidence_band": band,
            "route_should_route": route.should_route,
            "route_queue": route.queue,
            "route_reason_code": route.reason_code,
            "final_answer_after_gate": _redact(grounding.answer.text),
            "mock_grounded": mock_grounding.grounded,
            "gold_grounded_match": gold_grounded_match,
            "gold_routed_match": gold_routed_match,
        })

        gm = "" if gold_grounded_match is None else (" gold_g=OK" if gold_grounded_match else " gold_g=MISMATCH")
        rm = "" if gold_routed_match is None else (" gold_r=OK" if gold_routed_match else " gold_r=MISMATCH")
        print(f"  [{i:>3}/{total}] {rec['id']:<16} {rec['source']:<16} "
              f"grounded={int(grounding.grounded)} cit={len(live_draft.citations)} "
              f"conf={conf.score:.3f}[{band[:3]}] route={int(route.should_route)}"
              f"({route.reason_code or '-'}){gm}{rm}")
        time.sleep(0.05)

    _write_files(results, errors, DRAFT_MODEL, limit, total)


def _write_files(results: list[dict], errors: int, model: str, limit: int, total: int) -> None:
    graded = [r for r in results if r.get("exp_grounded") is not None or r.get("exp_routed") is not None]
    g_graded = [r for r in graded if r.get("exp_grounded") is not None and "error" not in r]
    r_graded = [r for r in graded if r.get("exp_routed") is not None and "error" not in r]
    g_ok = sum(1 for r in g_graded if r.get("gold_grounded_match"))
    r_ok = sum(1 for r in r_graded if r.get("gold_routed_match"))
    scored = [r for r in results if "error" not in r]
    grounded_n = sum(1 for r in scored if r.get("grounded"))
    routed_n = sum(1 for r in scored if r.get("route_should_route"))

    # ---- JSONL (machine-readable) ----
    jsonl_path = _REPO_ROOT / "redteam" / f"live_review_{limit}.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- Markdown (human-readable reviewer file) ----
    md_path = _REPO_ROOT / "redteam" / f"LIVE_REVIEW_{limit}.md"
    L: list[str] = []
    L.append(f"# Comet — Live Review Export ({len(scored)} inputs through the real {model})\n")
    L.append("Each input was run through the REAL production gates with the live `ClaudeLLM`. For every "
             "input below: the question + gold expectation, the retrieved evidence, the **raw answer the "
             "model wrote**, and the gate verdicts (grounding + which condition tripped + coverage numbers, "
             "confidence, routing). A reviewer can read each block to judge whether the system behaved well.\n")
    L.append("## Summary\n")
    L.append(f"- **Model:** `{model}` · **inputs:** {len(scored)} (of {total}) · **errors:** {errors} · `--limit={limit}`")
    L.append(f"- **Live grounded:** {grounded_n}/{len(scored)} · **routed for human review:** {routed_n}/{len(scored)}")
    L.append(f"- **vs GOLD grounding:** {g_ok}/{len(g_graded)} match `expected_grounded`"
             f"{' ✅' if g_ok == len(g_graded) else ' ⚠️'}")
    L.append(f"- **vs GOLD routing:** {r_ok}/{len(r_graded)} match `expected_routed`"
             f"{' ✅' if r_ok == len(r_graded) else ' ⚠️'}")
    L.append("- **Key:** read from untracked `.env`; redacted everywhere (RULE_NO_SECRET). No external send. ADD-only.\n")
    mismatches = [r for r in scored if r.get("gold_grounded_match") is False or r.get("gold_routed_match") is False]
    if mismatches:
        L.append(f"- ⚠️ **Gold mismatches to review:** {', '.join(r['id'] for r in mismatches)}\n")
    else:
        L.append("- ✅ **No gold mismatches** — every graded input matched its expected gold.\n")
    L.append("---\n")

    for idx, r in enumerate(results, start=1):
        L.append(f"## {idx}. `{r['id']}`  ·  source: `{r['source']}`")
        if "error" in r:
            L.append(f"\n> **ERROR (safe-terminal):** {r['error']}\n\n---\n")
            continue
        gold = []
        if r["exp_grounded"] is not None:
            gold.append(f"expected_grounded={r['exp_grounded']}")
        if r["exp_routed"] is not None:
            gold.append(f"expected_routed={r['exp_routed']}")
        if r.get("exp_queue"):
            gold.append(f"expected_queue={r['exp_queue']}")
        gold_str = (" · GOLD: " + ", ".join(gold)) if gold else " · (no gold — report-only)"
        L.append(f"\n**Question:** {_redact(r['question'])}")
        L.append(f"\n**Topic tags:** `{r['topic_tags']}`{gold_str}")
        L.append(f"\n**Retrieved chunks:** {r['retrieved_chunk_ids']}  (sensitivities: {r['retrieved_sensitivities']})")
        L.append("\n**RAW LLM ANSWER (what the model wrote):**\n")
        L.append("```")
        L.append(r["llm_answer_raw"])
        L.append("```")
        d = r["grounding_diag"]
        L.append(f"\n**Gate verdicts:**")
        L.append(f"- citations parsed: `{r['llm_citations']}`  (need ≥ {d['min_citations']})")
        if d["fabricated_citations"]:
            L.append(f"- ⚠️ fabricated citations (not retrieved): `{d['fabricated_citations']}`")
        L.append(f"- content coverage: `{d['coverage']}` (min `{d['coverage_min']}`) · "
                 f"question-coverage: `{d['question_coverage']}` (min `{d['question_coverage_min']}`)")
        L.append(f"- **grounded: `{r['grounded']}`**"
                 + (f" — failed condition `{d['failing_condition']}`" if d["failing_condition"] else " — all conditions passed"))
        L.append(f"- confidence: `{r['confidence_score']}` `[{r['confidence_band']}]` · "
                 f"routing: should_route=`{r['route_should_route']}` queue=`{r['route_queue']}` "
                 f"reason=`{r['route_reason_code']}`")
        if not r["grounded"]:
            L.append(f"- final answer after gate: `{r['final_answer_after_gate']}`")
        verdicts = []
        if r["gold_grounded_match"] is not None:
            verdicts.append("grounding " + ("✅ matches gold" if r["gold_grounded_match"] else "⚠️ MISMATCH vs gold"))
        if r["gold_routed_match"] is not None:
            verdicts.append("routing " + ("✅ matches gold" if r["gold_routed_match"] else "⚠️ MISMATCH vs gold"))
        if verdicts:
            L.append(f"- **vs gold:** {' · '.join(verdicts)}")
        L.append("\n---\n")

    md_path.write_text(_redact("\n".join(L)) + "\n", encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"  inputs scored: {len(scored)}   errors: {errors}")
    print(f"  live grounded: {grounded_n}/{len(scored)}   routed: {routed_n}/{len(scored)}")
    print(f"  vs gold grounding: {g_ok}/{len(g_graded)}   vs gold routing: {r_ok}/{len(r_graded)}")
    if mismatches:
        print(f"  ⚠️ gold mismatches: {', '.join(r['id'] for r in mismatches)}")
    else:
        print("  ✅ no gold mismatches")
    print("=" * 78)
    print(f"\n[files] reviewer Markdown : {md_path.relative_to(_REPO_ROOT)}")
    print(f"[files] machine JSONL     : {jsonl_path.relative_to(_REPO_ROOT)}")
    print("        (both key-redacted, ADD-only, local)\n")


if __name__ == "__main__":
    main()
