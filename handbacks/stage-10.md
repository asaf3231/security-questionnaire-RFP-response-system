# Stage 10 Handback — Intelligent Query Refinement (+ draft `<thinking>` removal)

**Executer:** PM-as-executer (Asaf-directed in-session), then PM cleanup 2026-06-28
**Dates:** implemented 2026-06-27 (`fe453f4`); brief/handback + revision + reconciliation 2026-06-28
**Stage:** 10 — Intelligent Query Refinement
**Boundary:** at the Stage-10 boundary; Stage 9 (Brief/Appendix) authored in the same 2026-06-28 pass.

> Authored retroactively to close the missing-handback governance gap (the per-stage handback was never
> written on disk when Stage 10 first landed). Pairs with `briefs/stage-10.md`.

---

## 1. What changed

### Files created (ADD-only)
- `app/query_optimizer.py` — `strip_thinking_block` (depth-aware deterministic strip) + `refine_query`.
- `tests/test_stage10_query_refinement.py` — `QREF*` / `DRAFT-COT*` coverage.

### Files modified (additive contracts, Asaf-directed)
- `app/llm.py` — `LLMProvider.refine_query` identity default; `ClaudeLLM.refine_query`; QUESTION block in
  the draft prompt; defensive `<thinking>` strip in `ClaudeLLM.draft`.
- `app/schema.py` — `ContextStack.question` (default `""`, backward-compatible).
- `app/context_stack.py` — carries the question into the stack.
- `app/pipeline.py` — `refine_query` + audit `tool_call` before retrieve.
- `scripts/run_live_draft.py` — raw→optimized display + no-leak check.

### 2026-06-28 cleanup (this pass)
- **Draft `<thinking>` scaffold removed** (live-grounding evidence) — `app/llm.py` draft prompt now
  requests inline citations + answer-only; dead `_DRAFT_THINKING_DIRECTIVE` constant deleted.
- **Two-key COT-test retirement** in `tests/test_stage10_query_refinement.py`: replaced
  `test_build_prompt_includes_thinking_directive` with `test_build_prompt_requests_inline_citations_answer_only`
  (positive assertion of the new contract) and removed `test_draft_directive_has_three_checks`. Spec-first
  provenance notes are inline in the test file. Key 2 = PM re-ran the failing test at the pre-edit revision
  (`7612e8a`): it **passed** against committed `llm.py` and **failed** only with the prompt edit ⇒ a code/spec
  change, not test-weakening.
- **Nested-tag bug fixed** in `strip_thinking_block` (non-greedy regex → depth-aware scan); 4 nested-case
  tests ADDED.
- **Magic numbers → `config.py` §9:** `REFINE_MAX_TOKENS`, `MAX_REFINED_QUERY_CHARS`.
- **`refine_query` audit event** now sets `to_state` (consistency with sibling `tool_call` events).
- **Unused imports dropped:** `datetime` (schema.py), `Citation` (pipeline.py), redundant
  `route_for_review` (run_live_suite.py); `argparse` removed from `run_chat.py` (stdlib-only `--live`).

## 2. DoD — `QREF1`–`QREF3`, `DRAFT-COT1`–`DRAFT-COT2`: ✅ test-verified
See `QA_checklist.md` §16. All green; nested-tag regression added under `QREF1`.

## 3. QA results (PM-run, this pass)
- Offline suite: green (see `FACTS.md` suite row for the verified count + commit).
- `make eval`: recall@k 1.0 · grounding match 1.0 / raw_grounded 0.833 · routing 1.0 · calibration
  exposes review{ungrounded=1} — **unchanged** from Stage 7r (MockLLM identity ⇒ no offline drift).
- `make demo`: clean; demo confidence scores unchanged.
- Import-safe: all 16 `app/` modules import side-effect-free (incl. `app.query_optimizer`).

## 4. Decisions made
- Keep the draft `<thinking>` removal (live evidence) — Asaf, 2026-06-28.
- Legitimize Stage 10 retroactively (this brief+handback+`/code-review`+sign-off) — Asaf, 2026-06-28.

## 5. DECISION-NEEDED — none open
The graded-contract additions + the COT-test retirement carry Asaf's explicit authorization (recorded in
`PM_LOG.md` + `NOTES.md`). The ghost "Stage 10 — KB expansion" plan is tombstoned (superseded; never built).

## 6. Deviations / risks
- The in-`<thinking>` sensitivity self-check was always defense-in-depth only; enforcement stays at the
  code chokepoints (`CLAUDE.md` §5).
- Live grounding is materially lower than offline mock grounding — expected and correct (the gate forces
  `UNGROUNDED_PLACEHOLDER` when the live model omits inline citations; nothing can self-approve or send
  externally). Surfaced for the Brief/Appendix.

## 7. Next recommended action
Final verification + commit on `redteam/crazy-testing`; record the `FACTS.md` suite row sha.
