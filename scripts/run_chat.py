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

import os
import sys
from pathlib import Path

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
After a question you'll be prompted for optional comma-separated topic tags
(e.g. "security" or "legal" — a high-risk tag forces routing to a human)."""


def _sep(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _make_provider(live: bool):
    """Return (provider, mode_label). Falls back to offline if a live key is missing."""
    from app.llm import ClaudeLLM, MockLLM

    if live:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            print("  ⚠️  live lane requested but ANTHROPIC_API_KEY is not set "
                  "— staying OFFLINE (MockLLM).")
            return MockLLM(), "offline (MockLLM)"
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

    # Transparency: show the candidates the retriever scores over (offline this is exactly
    # what the pipeline retrieves on; the live lane refines the query first, so its set may
    # differ slightly — noted below).
    candidates = retriever.retrieve(question, topic_tags=tags if tags else None)

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
    if mode.startswith("LIVE"):
        print("  (live lane refines the query first — retrieved set may differ slightly)")

    # ---- Retrieved evidence panel ----
    print("\nRetrieved evidence (top BM25 candidates):")
    if not candidates:
        print("  (none — no approved KB chunk matched)")
    else:
        for c in candidates:
            preview = c.answer[:70].replace("\n", " ")
            if len(c.answer) > 70:
                preview += "..."
            print(f"  [{c.chunk_id}]  score={c.bm25_score:.3f}  sens={c.sensitivity}")
            print(f"            {preview}")

    if not result.response_doc.items:
        print("\n(no result produced)")
        _sep("=")
        return

    doc_item = result.response_doc.items[0]
    routing = result.routing.get(item_id)
    score = doc_item.confidence_score
    band = confidence_band(score) if score is not None else "n/a"

    if item_id in result.errors:
        print(f"\n⚠️  component error (safe-terminal): {result.errors[item_id]}")

    # ---- Comet's answer ----
    print("\nComet's answer:")
    if doc_item.draft_text == UNGROUNDED_PLACEHOLDER:
        print(f"  {UNGROUNDED_PLACEHOLDER}")
        print("  (no grounded evidence found — routed for human input)")
    else:
        print(f"  {doc_item.draft_text}")

    cited = [c.chunk_id for c in doc_item.citations]
    print(f"\nCitations : {cited if cited else '(none)'}")
    if score is not None:
        print(f"Confidence: {score:.3f}  [{band}]")
    print(f"State     : {doc_item.status}")
    if routing is not None and routing.should_route:
        print(f"Routing   : ⚠️  ROUTED → queue={routing.queue!r}  reason={routing.reason_code}")
        print(f"            {REVIEW_BANNER}")
    else:
        print("Routing   : ✓  confident draft — NOT routed "
              "(still awaits a human APPROVED before any export)")
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

        # A question. Offer optional topic tags (these can trigger high-risk routing).
        try:
            tags_raw = input("   Tags (comma-sep, Enter=none): ").strip()
        except (EOFError, KeyboardInterrupt):
            tags_raw = ""
            print()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

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
