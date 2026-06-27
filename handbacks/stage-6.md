# Stage 6 Handback — End-to-end pipeline + two demo cases

Date: 2026-06-27
Executer: general-purpose cold subagent

---

## 1. What changed

### Files created
- `app/pipeline.py` — `run_pipeline()` + `PipelineResult`; the full orchestration layer (PIPE1/PIPE2)
- `scripts/run_demo.py` — `make demo` (offline/MockLLM); runs both demo cases, simulates human gate, exports (DEMO1/DEMO2)
- `scripts/run_live_draft.py` — `make demo-live` (gated); clean skip + exit 0 if no `ANTHROPIC_API_KEY`
- `scripts/__init__.py` — package marker; no side effects
- `tests/test_stage6.py` — 46 new tests (ENV4 progressive, PIPE1/PIPE2, DEMO1/DEMO2, RULE1/RULE2)
- `handbacks/stage-6.md` — this file

### Files modified
- `app/config.py` — added `ERROR_TERMINAL = "ERROR_TERMINAL"` (additive; §5.1 last reason-code)
- `app/retrieval.py` — added `Retriever` class; refactored module-level `retrieve()` to delegate to it (Asaf req #2, D-S6)
- `Makefile` — added `demo` + `demo-live` targets; added both to `.PHONY`

### Key implementation details

**`Retriever` class (`app/retrieval.py`):**
- Builds `BM25Okapi` over the full approved corpus ONCE at `__init__` time (standard RAG pattern, D-S6)
- `retrieve()` scores the query against the full-corpus index, then applies topic/sensitivity filters to the scored results, then returns top-k with deterministic `(-score, chunk_id)` sort
- Module-level `retrieve()` delegates to `Retriever(load_kb())` — one retrieval code path, backward-compatible signature

**`run_pipeline()` (`app/pipeline.py`):**
- Per-item chain: INTAKE → retrieve → RETRIEVED → assemble_context → draft_answer + grounding_check → DRAFTED → score_confidence → SCORED → route_for_review → (ROUTED_FOR_REVIEW or leave at SCORED)
- Audits every state transition and tool call (`RULE_AUDIT_COMPLETE`)
- `RULE_SAFE_TERMINAL` per-item `try/except`: any failure → `ROUTED_FOR_REVIEW` + `UNGROUNDED_PLACEHOLDER` + `ERROR_TERMINAL` audit event; never an uncaught exception
- `RULE_NO_SELF_APPROVE`: the pipeline (actor="agent") never transitions to `APPROVED`/`EXPORTED`; leaves confident items at `SCORED`
- `PipelineResult` carries `response_doc`, `routing` (dict), `errors` (dict)

**`scripts/run_demo.py`:**
- Runs both demo cases (MockLLM, fully offline)
- Per-item readable summary: question, confidence + band, routing decision, draft preview
- Simulates human gate: for `SCORED` non-routed items with no `internal`/`restricted` sensitivity, calls `transition(..., actor="human")` → `APPROVED`, then `export_response`
- DEMO1 i3 labeled as defense-in-depth showcase in printout
- DEMO2 items labeled as pending human review; `REVIEW_BANNER` confirmed in output

**`scripts/run_live_draft.py`:**
- Calls `load_env()` inside `main()` only; checks `ANTHROPIC_API_KEY` immediately after
- Clean skip path: prints "live lane requires ANTHROPIC_API_KEY — skipping" + `sys.exit(0)` if absent
- When key present: runs pipeline on `case_confident` with `ClaudeLLM`; simulates human gate; exports locally

---

## 2. DoD checklist

| QA ID | Status | Notes |
|---|---|---|
| `PIPE1` | ✅ test-verified | `TestPIPE1` (8 tests): happy path, ResponseDoc produced, deterministic under MockLLM, audit log written, routing dict populated, no errors on clean run |
| `PIPE2` | ✅ test-verified | `TestPIPE2` (4 tests): raising provider + raising retriever → ROUTED_FOR_REVIEW + UNGROUNDED_PLACEHOLDER + ERROR_TERMINAL audit; no uncaught exception |
| `DEMO1` | ✅ test-verified | `TestDEMO1` (6 tests): case_confident i1/i2 not routed at SCORED; i3 ROUTED_HIGH_RISK→security; grounded drafts; agent never self-approves |
| `DEMO2` | ✅ test-verified | `TestDEMO2` (6 tests): all case_review items ROUTED_FOR_REVIEW; RULE_HITM_REVIEW_TRIGGER fires; REVIEW_BANNER present; items never exported |
| `RULE1` | ✅ test-verified | `TestRULE1` (9 tests): every RULE_* in config.py greps to its §5.1 chokepoint; ERROR_TERMINAL in config + pipeline |
| `RULE2` | ✅ test-verified | `TestRULE2` (7 tests): ROUTED_HIGH_RISK, EXTERNAL_SEND_BLOCKED, SENSITIVITY_HOLD, SELF_APPROVE_BLOCKED, ERROR_TERMINAL all appear in audit logs on trigger |
| `ENV4` (progressive) | ✅ test-verified | `TestENV4Stage6`: app.pipeline imports cleanly (subprocess + in-process); no side effects; PipelineResult + run_pipeline importable |

---

## 3. QA results

**Full suite:** `278 passed / 1 skipped` (baseline was 232+1; +46 new tests; 0 regressions)

**Stage 6 only:** `46 passed / 0 failed` (`.venv/bin/pytest tests/test_stage6.py -v`)

**RET1–RET3 (verifier-independence):** all 32 Stage 2 tests pass post-refactor

**Recall@K (post-refactor):** `1.0` (computed via `compute_recall_at_k` over 12 labeled fixtures)
- Meets `RECALL_AT_K_TARGET = 0.90`
- Full-corpus index (filter-after-score) yields same recall as the previous filter-before-score approach on this corpus
- No RET test modified; no fixture tuned

**`make demo` (offline):** runs cleanly; both cases execute; DEMO1 exports i1; DEMO2 stays routed; REVIEW_BANNER confirmed; no network; no ANTHROPIC_API_KEY required

**`make demo-live` (gated):** skip path confirmed (exits 0 with clear message when key absent); when key present, live lane runs ClaudeLLM, writes local exports only

**Safe-terminal (PIPE2):** no uncaught exception escapes `run_pipeline()` under injected failures (verified by 4 dedicated tests)

**No existing test modified:** confirmed (diff touches only new/modified files listed above; no `RET*`/`CONF*`/`ROUTE*`/`STATUS*`/`AUDIT*`/`EXPORT*`/`BOUND*` tests touched)

---

## 4. Decisions made

- **Full-corpus index filter order:** BM25 index built over all approved chunks; filters applied post-scoring. This is the standard RAG pattern (stable IDF weights) and produces identical Recall@K = 1.0. Recall@K is unchanged; no DECISION-NEEDED.
- **i2 sensitivity in demo:** `case_confident-i2` cites `kb-009` (internal) as part of its MockLLM response (MockLLM cites all chunks in the retrieval layer). `RULE_SENSITIVITY_GATE` correctly withholds it from the simulated human approval in `run_demo.py`. Only i1 is auto-approved/exported. This is correct behavior — the sensitivity gate is working as intended.
- **sys.path in scripts:** added `sys.path.insert(0, repo_root)` at top of each script so `import app.*` resolves when run as `python scripts/run_demo.py` from the repo root (matching `conftest.py` approach for tests).
- **`RULE_AUDIT_COMPLETE` as default rule on non-governance events:** used as the `rule` field on routine audit events (tool calls, state transitions without a specific RULE_* trigger). This follows the pattern from Stages 5 and 3.

---

## 5. DECISION-NEEDED

None. No graded contracts changed. Recall@K = 1.0 post-refactor (no drop below target). No RET test modified.

---

## 6. Deviations / risks

- None from `PLAN.md`. All Stage 6 scope items delivered.
- Unpinned deps: none added; `app/pipeline.py` imports only stdlib + existing app.* modules already in `requirements.txt`.
- The `make demo-live` output in this session used the real Claude API (key was in the test environment). The gating check is correct: when `ANTHROPIC_API_KEY` is absent from both `.env` and the process environment, the script prints the skip message and exits 0.

---

## 7. Next recommended action

**PM verification:** re-run `make test` (verify 278+/1-skip), `make demo` (verify both demo cases execute offline cleanly), manually confirm DEMO1 exports i1 and DEMO2 exports nothing. Re-measure Recall@K = `1.0` via `compute_recall_at_k`. Run `/code-review` on the Stage 6 diff (pipeline orchestration touches graded contracts). Record the post-refactor Recall@K in `FACTS.md`. Then advance to **Stage 7 — Offline evaluation harness**.
