# Brief — Stage 6: End-to-end pipeline + the two demo cases

Read first (in order): `CLAUDE.md` (esp. §3.1 pipeline shape, §5 `RULE_SAFE_TERMINAL`, §6) →
`PLAN.md` (Stage 6) → `QA_checklist.md` (`PIPE1`–`PIPE2`, `DEMO1`–`DEMO2`, `RULE1`–`RULE2`) →
`NOTES.md` (D-S6 + the open follow-ups), then this brief.

Goal: wire the full agent (intake→export) into `app/pipeline.py`, build the BM25 index once, ship the
two demo scripts + Makefile targets, and prove safe-terminal + full `RULE_*` coverage. The first
fully runnable agent. Fully offline + deterministic for the graded suite.

## Scope — do ONLY this stage

### 0. `app/config.py` — NEW reason-code (additive; do NOT alter existing values)
- `ERROR_TERMINAL = "ERROR_TERMINAL"` (the last §5.1 audit reason-code; `app/pipeline.py` chokepoint).

### 1. Retrieval refactor — build the BM25 index ONCE (Asaf req #2; D-S6)
- Add a **`Retriever`** class to `app/retrieval.py`:
  ```python
  class Retriever:
      def __init__(self, chunks: list[RetrievedChunk]) -> None: ...   # build BM25Okapi over approved chunks ONCE
      def retrieve(self, question: str, *, topic_tags=None, allowed_sensitivities=None,
                   top_k: int = RETRIEVAL_TOP_K) -> list[RetrievedChunk]: ...
  ```
  It scores the query against the **full approved-corpus** index, then applies the topic/sensitivity
  filters to the results, then returns top-k (same deterministic `(-score, chunk_id)` sort).
- **Refactor the module-level `retrieve()` to delegate** to `Retriever(load_kb())` (preserve its exact
  signature + return type) so there is ONE retrieval code path. The pipeline builds ONE `Retriever`
  at init and reuses it across all items (the perf fix).
- **GUARDRAIL (verifier-independence):** run `RET1`–`RET3` + `compute_recall_at_k`. They MUST stay
  green and Recall@K MUST stay ≥ `RECALL_AT_K_TARGET`. If the refactor would break a RET test or drop
  Recall@K below target, **STOP and surface DECISION-NEEDED** — do NOT modify any RET test, do NOT
  tune fixtures. Report the measured Recall@K (it may differ from Stage-2's 1.0; that's fine if ≥ target).

### 2. `app/pipeline.py` — the E2E pipeline (graded; `RULE_SAFE_TERMINAL`; `PIPE1`–`PIPE2`)
```python
@dataclass
class PipelineResult:
    response_doc: ResponseDoc
    routing: dict[str, RoutingDecision]   # item_id → decision
    errors: dict[str, str]                # item_id → error message (ERROR_TERMINAL items)

def run_pipeline(
    questionnaire: dict,                   # from app.kb.load_questionnaire()
    *,
    provider: LLMProvider | None = None,   # default MockLLM()
    retriever: Retriever | None = None,    # default: build once from load_kb()
    policy_tags: dict | None = None,       # default: load_policy_tags()
    audit_log_path: Path | None = None,
) -> PipelineResult:
```
Per item, run the chain and **audit every transition + tool call** (`RULE_AUDIT_COMPLETE`):
INTAKE → `retriever.retrieve` → RETRIEVED → `assemble_context` → `draft_answer`+`grounding_check`
→ DRAFTED → `score_confidence` → SCORED → `route_for_review`:
  - trigger fires → `transition(SCORED→ROUTED_FOR_REVIEW, actor="agent")` (allowed).
  - no trigger → **leave at SCORED** (a confident draft awaiting a human `APPROVED` — the agent
    **never** self-approves, `RULE_NO_SELF_APPROVE`).
Build a `ResponseDocItem` per item: `question`, `draft_text`, `citations`, `confidence_score`,
`status` (final agent state), `queue` (if routed), `sensitivities` (the cited chunks' sensitivity tags),
`review_approved=False`. Assemble a `ResponseDoc`.
- **`RULE_SAFE_TERMINAL` (`PIPE2`):** wrap each item in try/except — ANY component failure
  (malformed chunk, empty retrieval, provider raise, validation error) → set the item to a safe
  terminal (`ROUTED_FOR_REVIEW`) with `draft_text = UNGROUNDED_PLACEHOLDER`, record the message in
  `errors[item_id]`, and `write_audit(... rule=RULE_SAFE_TERMINAL, detail includes ERROR_TERMINAL ...)`.
  **No uncaught exception may escape `run_pipeline`.**
- Deterministic under `MockLLM` (`PIPE1`): same questionnaire ⇒ same `ResponseDoc`.

### 3. Demo scripts + Makefile (`DEMO1`–`DEMO2`)
- `scripts/run_demo.py` (`make demo`, **mocked, offline, no network**): run `run_pipeline` over BOTH
  `case_confident` and `case_review`; print a readable per-item summary (question, draft/placeholder,
  confidence + band, routed?/queue + reason_code, status). Then **simulate the human gate**: for
  confident non-sensitive items (`status==SCORED`, not routed, no internal/restricted sensitivity),
  `transition(SCORED→APPROVED, actor="human")`, set `review_approved`/status, and call
  `export_response`. Print the export paths + audit path. The output must make the two cases obvious:
    - **DEMO1** — `case_confident` i1/i2: confident, grounded, **not routed** → human-approved →
      exported. i3: high score but **ROUTED_HIGH_RISK→security** (the defense-in-depth showcase —
      label it as such in the printout).
    - **DEMO2** — `case_review`: `RULE_HITM_REVIEW_TRIGGER` fires → `ROUTED_FOR_REVIEW` to the right
      queue with `REVIEW_BANNER` in the preview → **never exported** (awaits human).
- `scripts/run_live_draft.py` (`make demo-live`, **gated**): `load_env()`; if no `ANTHROPIC_API_KEY`,
  print a clear "live lane requires ANTHROPIC_API_KEY — skipping" and exit 0. Else run the pipeline on
  ONE case with `provider=ClaudeLLM()` to show a real-model draft; still **no external send**.
- `Makefile`: add `demo` (`python scripts/run_demo.py`) and `demo-live` (`python scripts/run_live_draft.py`).
- `scripts/__init__.py` if needed for imports; scripts call `load_env()` only inside `main()` (never at import).

### 4. `RULE_*` coverage (`RULE1`–`RULE2`)
- `RULE1` — for each `RULE_*` string in `config.py` §9, grep proves it is referenced at the chokepoint
  module named in `CLAUDE.md` §5.1 (no orphan rule).
- `RULE2` — a pipeline run (or a dedicated test) that triggers each rule writes its reason-code to the
  audit log: `GROUNDING_FAIL`, `ROUTED_HIGH_RISK`/`ROUTED_AMBIGUOUS`/`ROUTED_LOW_CONFIDENCE`,
  `SELF_APPROVE_BLOCKED`, `SENSITIVITY_HOLD`, `EXTERNAL_SEND_BLOCKED`, `ERROR_TERMINAL`.

### 5. Tests (`PIPE1`–`PIPE2`, `DEMO1`–`DEMO2`, `RULE1`–`RULE2`) + progressive ENV4
- Add `app.pipeline` to the ENV4-progressive test (addition). Use `tmp_path` for audit/export writes.
- `DEMO1`/`DEMO2` tests assert the behaviors above by running `run_pipeline` on the real demo
  questionnaires (deterministic under MockLLM).

## QA checks to PASS (run, not inspect): `PIPE1`–`PIPE2`, `DEMO1`–`DEMO2`, `RULE1`–`RULE2`, plus `RET1`–`RET3`+Recall@K stay green; `make test` green; `make demo` runs clean offline; `ENV4` clean.

## Constraints (from CLAUDE.md)
- Import-safe (no client/network/.env/data read/file write at import; scripts load `.env` only in `main`).
- Deterministic offline (`MockLLM`, seeded); no inline magic values; reason-codes/literals from §9.
- The agent NEVER self-approves (`RULE_NO_SELF_APPROVE`); no external send (`RULE_NO_EXTERNAL_SEND`).
- `RULE_SAFE_TERMINAL`: an uncaught exception anywhere in `pipeline.py` is a defect.

## Do NOT
- Touch the spine docs (PM-owned). Adding `ERROR_TERMINAL` to `config.py` + the `Retriever` class +
  `pipeline.py` IS in scope; do NOT change any EXISTING §9 value, schema field, byte-exact literal, or `RULE_*`.
- **Modify any existing graded test (`RET*`/`CONF*`/`ROUTE*`/`STATUS*`/`AUDIT*`/`EXPORT*`/`BOUND*`) to
  make it pass** (verifier-independence). If the retrieval refactor breaks a RET test or drops
  Recall@K, HALT as DECISION-NEEDED. Adding new tests / the ENV4 module is fine. Do not commit.
- Advance past Stage 6.

## Deliver
Write `handbacks/stage-6.md` (CLAUDE §12.1 format). Report: `make test` pass/skip count, the
**re-measured Recall@K** (post-refactor), files created/modified (call out `ERROR_TERMINAL` + the
`Retriever` class), each `PIPE*`/`DEMO*`/`RULE*` ✅/⚠️ (test-verified), confirmation `make demo` runs
clean offline + safe-terminal holds (no uncaught exception), any DECISION-NEEDED (esp. if RET/Recall@K
shifted), one next action. Return it as your final message. The PM re-runs everything, re-verifies
Recall@K + the two demo behaviors + safe-terminal independently, runs `/code-review`, records in `FACTS.md`.
