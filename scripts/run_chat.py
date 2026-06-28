"""
scripts/run_chat.py — make chat (interactive terminal REPL).

Responsibility: let a user type a security-questionnaire question in the terminal and
watch Comet respond end-to-end through the REAL pipeline — retrieve → assemble → draft →
grounding gate → confidence → routing — printing a transparent per-turn panel (retrieved
chunks, draft, citations, confidence + band, routing decision).

This is an ADD-only operational demo wrapper. It changes no app module, no graded contract,
and no test/fixture — it reuses app.pipeline.run_pipeline with an injected provider and a
build-once Retriever (the same path `make demo` uses).

Lanes:
  - default: MockLLM (offline, deterministic, no key, no network) — rehearsal-safe.
  - --live : ClaudeLLM (gated live lane) — requires ANTHROPIC_API_KEY in .env. Falls back
             to offline if the key is missing. Switch mid-session with :live / :mock.

Governance:
  - RULE_NO_EXTERNAL_SEND: reads stdin / prints stdout only; the only outbound call is the
    gated Claude API in --live mode (the one permitted call). Nothing is sent externally.
  - RULE_NO_SELF_APPROVE: this REPL is read-only — it never approves or exports. Items end
    at SCORED (a confident draft awaiting a human) or ROUTED_FOR_REVIEW.

Import-safe: no side effects at import; load_env() and all app imports happen in main().
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Enable line editing + in-session history at the input() prompt (↑ recalls the previous
# question, ←/→ and backspace edit). `readline` is stdlib but POSIX-only (absent on Windows),
# so it is imported optionally via importlib — the correct cross-platform pattern for a
# platform-specific stdlib module (and ENV2 needs nothing pinned for a stdlib import).
import importlib
try:
    importlib.import_module("readline")
except ImportError:
    pass

# Ensure the repo root is on sys.path so `import app.*` resolves when run as
# `python scripts/run_chat.py` from the repo root (mirrors scripts/run_demo.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_HELP = """\
Commands:
  <your question>   ask Comet a security-questionnaire question
  :live             switch to the live Claude lane (needs ANTHROPIC_API_KEY)
  :mock             switch to the offline MockLLM lane (default)
  :mode             show the current lane
  :help             show this help
  :quit             exit  (also Ctrl-D / Ctrl-C)
Topic tags are inferred automatically from the retrieved evidence (auto-tagging at
intake); an inferred high-risk tag (e.g. legal/security) forces routing to a human."""


def _sep(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _read_new_events(path: Path, start: int) -> list[dict]:
    """Read audit JSONL events appended at/after byte offset `start` (this turn's events).

    The pipeline appends one whole event per line, so `start` (the log size captured before
    the run) is always a line boundary — reading the tail yields exactly this turn's steps
    without scanning or re-parsing the whole growing file.
    """
    events: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fh.seek(start)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return events


def _make_provider(live: bool):
    """Return (provider, mode_label). Falls back to offline if a live key is missing."""
    from app.llm import ClaudeLLM, MockLLM

    if live:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            print("  ⚠️  live lane requested but ANTHROPIC_API_KEY is not set "
                  "— staying OFFLINE (MockLLM).")
            return MockLLM(), "offline (MockLLM)"
        # Surface the two Claude requests (prompt + response) in the REPL trace.
        os.environ["COMET_SHOW_PROMPTS"] = "1"
        return ClaudeLLM(), "LIVE (ClaudeLLM · claude-sonnet-4-6)"
    return MockLLM(), "offline (MockLLM)"


def _handle_question(
    question: str,
    tags: list[str],
    *,
    provider,
    mode: str,
    retriever,
    policy_tags: dict,
    audit_log_path: Path,
    qid: str,
) -> None:
    """Run one question through the real pipeline and print a transparent panel."""
    from app.config import REVIEW_BANNER, UNGROUNDED_PLACEHOLDER
    from app.confidence import confidence_band
    from app.pipeline import run_pipeline
    from app.schema import QuestionnaireItem

    item_id = f"{qid}-i1"
    questionnaire = {
        "questionnaire_id": qid,
        "items": [QuestionnaireItem(item_id=item_id, question=question, topic_tags=tags)],
    }

    # Read only THIS turn's audit events: record the log size before the run, then read the
    # tail afterwards (the pipeline writes one event per step — the canonical step record).
    audit_start = audit_log_path.stat().st_size if audit_log_path.exists() else 0

    result = run_pipeline(
        questionnaire,
        provider=provider,
        retriever=retriever,
        policy_tags=policy_tags,
        audit_log_path=audit_log_path,
    )

    print()
    _sep("=")
    print(f"Lane: {mode}")

    # ---- minimal per-step pipeline trace (one line per step, from the audit events) ----
    print("\nPipeline:")
    for ev in _read_new_events(audit_log_path, audit_start):
        if ev.get("event") != "tool_call":
            continue
        d = ev.get("detail") or {}
        tool = d.get("tool")
        if tool == "refine_query":
            opt = d.get("optimized") or ""
            if opt and opt != d.get("original"):
                print(f"  refine    → {opt[:76]}{'…' if len(opt) > 76 else ''}")
        elif tool == "retrieve":
            ids = d.get("chunk_ids") or []
            shown = ", ".join(ids[:5]) + ("…" if len(ids) > 5 else "")
            print(f"  retrieve  → {d.get('n_chunks', len(ids))} chunks: {shown or '(none)'}")
        elif tool == "auto_tag":
            t = d.get("inferred_tags") or []
            print(f"  auto-tag  → {', '.join(t) if t else '(none)'}")
        elif tool == "assemble_context":
            print(f"  assemble  → {d.get('n_retrieval_entries', 0)} evidence entries")
        elif tool == "draft_answer":
            rc = d.get("reason_code")
            print(f"  draft     → grounded={d.get('grounded')} · "
                  f"{d.get('n_citations', 0)} cit" + (f" · {rc}" if rc else ""))
        elif tool == "score_confidence":
            s = d.get("score")
            if s is not None:
                print(f"  score     → {s:.3f} [{confidence_band(s)}]")
        elif tool == "route_for_review":
            if d.get("should_route"):
                print(f"  route     → ⚠ {d.get('queue')} · {d.get('reason_code')}")
            else:
                print("  route     → ✓ not routed")

    if not result.response_doc.items:
        print("\n(no result produced)")
        _sep("=")
        return

    doc_item = result.response_doc.items[0]
    routing = result.routing.get(item_id)
    if item_id in result.errors:
        print(f"\n⚠️  component error (safe-terminal): {result.errors[item_id]}")

    # ---- the LLM response (the drafted answer) ----
    print("\nAnswer:")
    if doc_item.draft_text == UNGROUNDED_PLACEHOLDER:
        print(f"  {UNGROUNDED_PLACEHOLDER}")
        print("  (no grounded evidence found — routed for human input)")
    else:
        print(f"  {doc_item.draft_text}")
    cited = [c.chunk_id for c in doc_item.citations]
    print(f"\nCitations : {cited if cited else '(none)'}")
    if routing is not None and routing.should_route:
        print(f"  {REVIEW_BANNER}")
    _sep("=")


def _wants_live(argv: list[str]) -> bool:
    """Stdlib-only --live flag detection (argparse is not on the ENV2 import allowlist)."""
    return "--live" in argv


def main() -> None:
    """Entry point for `make chat` (offline default) / `make chat-live`."""
    live = _wants_live(sys.argv[1:])

    # load_env() here only — never at import (import-safe).
    from app.config import load_env
    load_env()

    from app.kb import load_kb, load_policy_tags
    from app.retrieval import Retriever

    audit_dir = _REPO_ROOT / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_log_path = audit_dir / "repl_session.jsonl"

    # Build the BM25 index ONCE; reuse it for every question (D-S6 build-once pattern).
    retriever = Retriever(load_kb())
    policy_tags = load_policy_tags()
    provider, mode = _make_provider(live)

    print()
    _sep("=")
    print("  COMET — RFP / Security-Questionnaire Response Agent  (make chat)")
    print(f"  Interactive demo · Lane: {mode}")
    _sep("=")
    print(_HELP)

    counter = 0
    while True:
        try:
            raw = input("\n📝 Question (:help, :quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            break

        if not raw:
            continue
        if raw in (":quit", ":q", ":exit"):
            print("bye.")
            break
        if raw in (":help", ":h"):
            print(_HELP)
            continue
        if raw == ":mode":
            print(f"  current lane: {mode}")
            continue
        if raw == ":live":
            provider, mode = _make_provider(True)
            print(f"  → switched to {mode}")
            continue
        if raw == ":mock":
            provider, mode = _make_provider(False)
            print(f"  → switched to {mode}")
            continue
        if raw.startswith(":"):
            print(f"  unknown command {raw!r} — type :help")
            continue

        # Topic tags are inferred automatically at intake (auto_tag) — no manual prompt.
        tags: list[str] = []

        counter += 1
        qid = f"repl-{counter:03d}"
        try:
            _handle_question(
                raw,
                tags,
                provider=provider,
                mode=mode,
                retriever=retriever,
                policy_tags=policy_tags,
                audit_log_path=audit_log_path,
                qid=qid,
            )
        except Exception as exc:  # never crash the REPL on a single bad turn
            print(f"  ⚠️  turn skipped — unexpected error: {exc!r}")

    print(f"\nAudit trail for this session: {audit_log_path}")
    print()


if __name__ == "__main__":
    main()
