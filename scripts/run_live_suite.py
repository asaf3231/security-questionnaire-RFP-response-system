"""
scripts/run_live_suite.py — ADD-only LIVE breadth harness (Asaf-authorized, option B).

Responsibility: drive the REAL production pipeline gates
(retrieve → assemble_context → draft → grounding_check → score_confidence →
route_for_review) through BOTH providers — the offline MockLLM and the live
ClaudeLLM — across a broad set of demo + eval + red-team inputs, and report how
the three governance gates (grounding / confidence / routing) behave live versus
the deterministic mock.

Why mock AND live: the live model's only influence on the gates flows through the
GROUNDING gate (does the live prose cite valid [chunk_id] markers with enough
lexical coverage?). Confidence changes only via the binary grounded term; routing
only via that. Running both providers makes every live divergence explicit and
attributable, instead of guessing.

Governance posture:
  * ADD-only. This is a NON-graded operational script (not under tests/). It
    modifies no locked test/fixture/app module and changes no graded contract.
  * RULE_NO_SECRET. The API key is read from the untracked .env via load_env();
    it is NEVER printed, written, or committed. Every captured/printed string is
    passed through _redact() which scrubs any sk-ant-... token defensively.
  * RULE_NO_EXTERNAL_SEND. This still sends nothing externally — it only calls the
    Claude API (the one permitted outbound call) and writes a local report.
  * RULE_SAFE_TERMINAL (spirit). Per-input failures are caught and recorded; the
    harness never crashes mid-run. A pre-flight connectivity probe aborts cleanly
    (before burning N calls) if the key is missing/invalid.

Import-safe: no work at import; everything happens inside main().

Usage:
    python scripts/run_live_suite.py [--limit N]   # default N=100 live calls
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


# Use only allowlisted stdlib (ENV2 import-scanner): no argparse / statistics.
def _parse_limit(argv: list[str], default: int = 100) -> int:
    """Tiny --limit parser (stdlib argparse is not on the ENV2 allowlist)."""
    for i, a in enumerate(argv):
        if a == "--limit" and i + 1 < len(argv):
            return int(argv[i + 1])
        if a.startswith("--limit="):
            return int(a.split("=", 1)[1])
    return default


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0

# Defensive secret scrubber — applied to EVERY string we print or write.
_SK_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")
_KEYWORD_RE = re.compile(r"(ANTHROPIC_API_KEY)\s*=\s*\S+")


def _redact(text: str) -> str:
    """Scrub any Anthropic secret token from a string (RULE_NO_SECRET defence-in-depth)."""
    if not isinstance(text, str):
        text = str(text)
    text = _SK_RE.sub("[REDACTED-SECRET]", text)
    text = _KEYWORD_RE.sub(r"\1=[REDACTED-SECRET]", text)
    return text


# Question length cap for live calls — keeps flood inputs from running up the token bill.
_MAX_LIVE_QUESTION_CHARS = 2000


def _gather_inputs() -> list[dict]:
    """Build a unified list of inputs from eval gold + demo questionnaires + the
    red-team matrix. Each record: {id, source, question, topic_tags, exp_grounded,
    exp_routed, exp_queue, exp_reason}. Expectations are None when the source has no gold."""
    from app.kb import load_questionnaire

    records: list[dict] = []

    # --- 1. Eval gold (has full gate expectations) ---
    eval_path = _REPO_ROOT / "fixtures" / "eval" / "eval_cases.synthetic.json"
    for c in json.loads(eval_path.read_text(encoding="utf-8")):
        records.append({
            "id": c["item_id"], "source": "eval", "question": c["question"],
            "topic_tags": c.get("topic_tags", []),
            "exp_grounded": c.get("expected_grounded"),
            "exp_routed": c.get("expected_routed"),
            "exp_queue": c.get("expected_queue"),
            "exp_reason": c.get("expected_reason"),
        })

    # --- 2. Demo questionnaires (no gold; report-only) ---
    for fname in ("case_confident.synthetic.json", "case_review.synthetic.json"):
        qpath = _REPO_ROOT / "data" / "questionnaires" / fname
        if qpath.exists():
            q = load_questionnaire(qpath)
            for item in q["items"]:
                records.append({
                    "id": item.item_id, "source": "demo", "question": item.question,
                    "topic_tags": item.topic_tags,
                    "exp_grounded": None, "exp_routed": None, "exp_queue": None, "exp_reason": None,
                })

    # --- 3. Red-team matrix (spec invariants → partial expectations) ---
    mpath = _REPO_ROOT / "tests" / "redteam" / "redteam_inputs.synthetic.json"
    if mpath.exists():
        for r in json.loads(mpath.read_text(encoding="utf-8")):
            if r.get("expect_construct_error"):
                continue  # empty/whitespace cases — validation, not a gate test
            q = r["question"]
            if r.get("inflate_to_bytes"):
                q = q * 4  # a representative non-trivial repeat (clipped below anyway)
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


def _run_gates(item, chunks, ctx, provider, *, question):
    """Run draft → ground → score → route for one provider over pre-computed chunks/ctx."""
    from app.confidence import confidence_band, score_confidence
    from app.config import UNGROUNDED_PLACEHOLDER
    from app.draft import draft_answer, grounding_check

    draft = draft_answer(ctx, provider=provider, question=question)
    grounding = grounding_check(draft, ctx, question=question)
    conf = score_confidence(chunks, grounding, question)
    return {
        "grounded": grounding.grounded,
        "placeholder": draft.text == UNGROUNDED_PLACEHOLDER,
        "n_citations": len(draft.citations),
        "score": round(conf.score, 4),
        "band": confidence_band(conf.score),
        "preview": _redact(draft.text)[:160].replace("\n", " "),
    }


def _route(item, chunks, score, policy):
    from app.routing import route_for_review
    from app.schema import ConfidenceResult
    d = route_for_review(item, chunks, ConfidenceResult(score=score), policy)
    return {"should_route": d.should_route, "queue": d.queue, "reason": d.reason_code}


def _preflight(provider) -> tuple[bool, str]:
    """One minimal live call to confirm the key/connectivity work. Returns (ok, message).
    The message is redacted; the secret never appears."""
    from app.config import _get_claude, DRAFT_MODEL
    try:
        client = _get_claude()
        resp = client.messages.create(
            model=DRAFT_MODEL, max_tokens=8, temperature=0.0,
            messages=[{"role": "user", "content": "ping"}],
        )
        txt = "".join(getattr(b, "text", "") for b in resp.content).strip()
        return True, _redact(f"live OK (model={DRAFT_MODEL}, replied {len(txt)} chars)")
    except Exception as exc:  # noqa: BLE001 — report type, never the key
        return False, _redact(f"{type(exc).__name__}: {exc}")


def main() -> None:
    limit = _parse_limit(sys.argv[1:], default=100)

    from app.config import load_env, DRAFT_MODEL
    load_env()

    import os
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("\nlive lane requires ANTHROPIC_API_KEY in .env — nothing to run.\n")
        sys.exit(0)

    from app.context_stack import assemble_context
    from app.kb import load_kb, load_policy_tags
    from app.llm import ClaudeLLM, MockLLM
    from app.retrieval import Retriever
    from app.schema import QuestionnaireItem

    print("=" * 78)
    print("  COMET — LIVE BREADTH HARNESS  (mock vs live, real ClaudeLLM, no external send)")
    print(f"  model={DRAFT_MODEL}  ·  limit={limit}  ·  key source=.env (redacted)")
    print("=" * 78)

    live = ClaudeLLM()
    mock = MockLLM()

    # ---- Pre-flight: one cheap live call; abort before burning N calls if it fails ----
    ok, msg = _preflight(live)
    print(f"\n[pre-flight] {msg}")
    if not ok:
        print("\n[pre-flight] live lane is NOT reachable — aborting before any breadth calls.")
        print("            (check the key in .env / rate limits; nothing was spent on the suite.)\n")
        sys.exit(1)

    retriever = Retriever(load_kb())
    policy = load_policy_tags()
    records = _gather_inputs()[: limit]
    total = len(records)
    print(f"[inputs] {total} inputs (eval + demo + red-team matrix), capped at --limit={limit}\n")

    rows: list[dict] = []
    errors = 0
    for i, rec in enumerate(records, start=1):
        question = rec["question"][:_MAX_LIVE_QUESTION_CHARS]
        try:
            item = QuestionnaireItem(item_id=rec["id"], question=question, topic_tags=rec["topic_tags"])
            chunks = retriever.retrieve(question, topic_tags=item.topic_tags or None)
            ctx = assemble_context(item, chunks, item_number=i, total_items=total)

            m = _run_gates(item, chunks, ctx, mock, question=question)
            l = _run_gates(item, chunks, ctx, live, question=question)
            m_route = _route(item, chunks, m["score"], policy)
            l_route = _route(item, chunks, l["score"], policy)
        except Exception as exc:  # noqa: BLE001 — never crash the harness
            errors += 1
            print(f"  [{i:>3}/{total}] {rec['id']:<14} ERROR {_redact(type(exc).__name__)}")
            continue

        rows.append({**rec, "mock": m, "live": l, "mock_route": m_route, "live_route": l_route})
        flip = "GROUND-FLIP" if m["grounded"] != l["grounded"] else ""
        rflip = "ROUTE-FLIP" if m_route != l_route else ""
        print(f"  [{i:>3}/{total}] {rec['id']:<14} {rec['source']:<16} "
              f"mock(g={int(m['grounded'])},{m['band'][:3]},rt={int(m_route['should_route'])}) "
              f"live(g={int(l['grounded'])},{l['band'][:3]},rt={int(l_route['should_route'])}) "
              f"cit={l['n_citations']} {flip}{(' '+rflip) if rflip else ''}")
        time.sleep(0.05)  # be gentle on rate limits

    _summarize(rows, errors, DRAFT_MODEL, limit)


def _summarize(rows: list[dict], errors: int, model: str, limit: int) -> None:
    if not rows:
        print("\nNo successful rows to summarize.\n")
        return

    n = len(rows)
    live_grounded = sum(r["live"]["grounded"] for r in rows)
    mock_grounded = sum(r["mock"]["grounded"] for r in rows)
    ground_flips = [r for r in rows if r["mock"]["grounded"] != r["live"]["grounded"]]
    route_flips = [r for r in rows if r["mock_route"] != r["live_route"]]
    band_flips = [r for r in rows if r["mock"]["band"] != r["live"]["band"]]
    live_no_cit = sum(1 for r in rows if r["live"]["n_citations"] == 0)

    # Gate accuracy vs gold (only where the source provides an expectation).
    g_graded = [r for r in rows if r["exp_grounded"] is not None]
    g_hit = sum(1 for r in g_graded if r["live"]["grounded"] == r["exp_grounded"])
    r_graded = [r for r in rows if r["exp_routed"] is not None]
    r_hit = sum(1 for r in r_graded if r["live_route"]["should_route"] == r["exp_routed"])

    live_scores = [r["live"]["score"] for r in rows]
    mock_scores = [r["mock"]["score"] for r in rows]

    print("\n" + "=" * 78)
    print("  SUMMARY — live gate behaviour vs the deterministic mock")
    print("=" * 78)
    print(f"  inputs scored        : {n}   (errors: {errors})")
    print(f"  GROUNDING            : mock grounded {mock_grounded}/{n}  |  live grounded {live_grounded}/{n}")
    print(f"     ground-flips      : {len(ground_flips)}  (live disagrees with mock)")
    print(f"     live drafts w/ 0 citations (→ gate forces ungrounded): {live_no_cit}/{n}")
    print(f"  CONFIDENCE           : mock score mean={_mean(mock_scores):.3f} median={_median(mock_scores):.3f}"
          f"  |  live mean={_mean(live_scores):.3f} median={_median(live_scores):.3f}")
    print(f"     band-flips        : {len(band_flips)}")
    print(f"  ROUTING              : route-flips (live vs mock): {len(route_flips)}")
    if g_graded:
        print(f"  vs GOLD grounding    : live matches expected_grounded on {g_hit}/{len(g_graded)}")
    if r_graded:
        print(f"  vs GOLD routing      : live matches expected_routed on {r_hit}/{len(r_graded)}")

    if ground_flips:
        print("\n  --- grounding flips (mock→live) ---")
        for r in ground_flips[:15]:
            print(f"    {r['id']:<14} {r['source']:<16} mock_g={int(r['mock']['grounded'])} "
                  f"live_g={int(r['live']['grounded'])} cit={r['live']['n_citations']} "
                  f"| live: \"{r['live']['preview'][:70]}\"")
    if route_flips:
        print("\n  --- routing flips (mock→live) ---")
        for r in route_flips[:15]:
            mr, lr = r["mock_route"], r["live_route"]
            print(f"    {r['id']:<14} {r['source']:<16} "
                  f"mock(rt={int(mr['should_route'])},{mr['reason']}) → "
                  f"live(rt={int(lr['should_route'])},{lr['reason']})")

    _write_report(rows, errors, model, limit, {
        "n": n, "mock_grounded": mock_grounded, "live_grounded": live_grounded,
        "ground_flips": ground_flips, "route_flips": route_flips, "band_flips": band_flips,
        "live_no_cit": live_no_cit, "g_hit": g_hit, "g_total": len(g_graded),
        "r_hit": r_hit, "r_total": len(r_graded),
        "mock_mean": _mean(mock_scores), "live_mean": _mean(live_scores),
    })


def _write_report(rows, errors, model, limit, agg) -> None:
    out = _REPO_ROOT / "redteam" / "LIVE_RUN_FINDINGS.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# Comet — Live Breadth Run (real ClaudeLLM through the production gates)\n")
    lines.append(f"- **Model:** `{model}`  ·  **inputs scored:** {agg['n']}  ·  **errors:** {errors}  ·  **--limit:** {limit}")
    lines.append("- **Provider:** `ClaudeLLM` (live) compared against `MockLLM` (deterministic) per input")
    lines.append("- **Key:** read from untracked `.env`; redacted everywhere (RULE_NO_SECRET). No external send.")
    lines.append("- **ADD-only:** non-graded operational script; no locked test/fixture/app module touched.\n")
    lines.append("## Gate overview\n")
    lines.append(f"| Gate | Mock | Live | Divergence |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| Grounding (grounded count) | {agg['mock_grounded']}/{agg['n']} | {agg['live_grounded']}/{agg['n']} | {len(agg['ground_flips'])} flips; {agg['live_no_cit']} live drafts had 0 citations |")
    lines.append(f"| Confidence (mean score) | {agg['mock_mean']:.3f} | {agg['live_mean']:.3f} | {len(agg['band_flips'])} band-flips |")
    lines.append(f"| Routing (decision) | — | — | {len(agg['route_flips'])} route-flips (live vs mock) |")
    if agg["g_total"]:
        lines.append(f"\n- **Live grounding vs gold:** {agg['g_hit']}/{agg['g_total']} match `expected_grounded`.")
    if agg["r_total"]:
        lines.append(f"- **Live routing vs gold:** {agg['r_hit']}/{agg['r_total']} match `expected_routed`.")
    lines.append("\n## Interpretation\n")
    lines.append("The live model influences the gates **only through grounding**: confidence changes "
                 "solely via the binary grounded term, and routing only via that. The dominant live effect "
                 "is whether the live prose echoes the `[chunk_id]` citation markers with enough lexical "
                 "coverage — if it does not, `grounding_check` (correctly, by its own rules) forces "
                 "`UNGROUNDED_PLACEHOLDER` and the item routes for human review. None of this can "
                 "self-approve or send externally — those boundaries are code, not model-dependent.\n")
    if agg["ground_flips"]:
        lines.append("## Grounding flips (mock→live)\n")
        lines.append("| id | source | mock | live | live citations |")
        lines.append("|---|---|---|---|---|")
        for r in agg["ground_flips"][:40]:
            lines.append(f"| {r['id']} | {r['source']} | {int(r['mock']['grounded'])} | "
                         f"{int(r['live']['grounded'])} | {r['live']['n_citations']} |")
    if agg["route_flips"]:
        lines.append("\n## Routing flips (mock→live)\n")
        lines.append("| id | source | mock reason | live reason |")
        lines.append("|---|---|---|---|")
        for r in agg["route_flips"][:40]:
            lines.append(f"| {r['id']} | {r['source']} | {r['mock_route']['reason']} | {r['live_route']['reason']} |")
    out.write_text(_redact("\n".join(lines)) + "\n", encoding="utf-8")
    print(f"\n[report] wrote {out.relative_to(_REPO_ROOT)} (key-redacted, ADD-only)")


if __name__ == "__main__":
    main()
