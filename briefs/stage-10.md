# Brief — Stage 10: Intelligent Query Refinement (+ reasoning-scaffolded draft, since revised)

> **Authored retroactively 2026-06-28** to close a governance gap: Stage 10 was implemented and
> committed (`fe453f4`) under an Asaf in-session architectural directive without a brief or handback on
> disk. This brief documents the directive, scope, the graded contracts it touched, and the subsequent
> live-evidence revision that removed the draft `<thinking>` scaffold. Read with `handbacks/stage-10.md`.

Read first (in order): `CLAUDE.md` (§5 governance, §8 notebook discipline / no-dead-code, §9 constants)
→ `PLAN.md` (Stage 10) → `QA_checklist.md` (§16 `QREF1`–`QREF3`, `DRAFT-COT1`–`DRAFT-COT2`) → `NOTES.md`
→ this brief.

## Goal
Add an LLM **QUERY_REFINEMENT** stage before retrieval (raw question → optimized BM25 search query via
synonym/technical expansion in the live lane), and route the **original** question into the draft prompt
(fixing a defect where the item question never reached the model). The live Refinement + Draft prompts
were scaffolded with `<thinking>` reasoning that code deterministically strips before any gate/export
sees it. **The offline/graded path is byte-identical** because `MockLLM` inherits the identity
`refine_query` default — deterministic retrieval, eval, and demo are unchanged.

## ⛔ Binding governance (held throughout)
- `RULE_GRADED_ARTIFACT_LOCK`: `tests/`+`fixtures/` add-only; `ALLOW_GRADED_EDIT` is a human-only key.
- `RULE_METRIC_FALSIFIABLE`: no `_simulate_*`; the eval keeps its real path + red negative case.
- Code restrains the model, not prompts: the in-`<thinking>` self-checks are **defense-in-depth UX
  only**; the `RULE_*` chokepoints remain the enforcement (`CLAUDE.md` §5).

## Scope — what shipped
- **NEW `app/query_optimizer.py`** — `strip_thinking_block` (deterministic, depth-aware `<thinking>`
  strip) + `refine_query(question, *, provider)` wrapper with safe fallback to the original question on
  any failure (`RULE_SAFE_TERMINAL` spirit).
- **`app/llm.py`** (additive) — `LLMProvider.refine_query` identity default (MockLLM inherits ⇒ offline
  identity), `ClaudeLLM.refine_query` override, `_REFINE_DIRECTIVE` scaffold, the draft prompt now
  carries the QUESTION block, and `ClaudeLLM.draft` defensively strips `<thinking>` before
  citations/gate/export.
- **`app/schema.py`** — `ContextStack.question` field (default `""`, backward-compatible).
- **`app/context_stack.py`** — carries the original question into the stack.
- **`app/pipeline.py`** — runs `refine_query` + audits it (`tool_call`) before retrieve.
- **`scripts/run_live_draft.py`** — raw→optimized display + a no-leak check.
- **NEW `tests/test_stage10_query_refinement.py`** — `QREF*` + `DRAFT-COT*` coverage (add-only).

## Graded contracts touched (additive, Asaf-directed)
`LLMProvider` interface (new optional method), `ContextStack` schema (new defaulted field),
`app/pipeline.py` chokepoint, the `_build_prompt`/`draft` prompt+strip path, and (Phase B 2026-06-28)
two new `app/config.py` §9 constants `REFINE_MAX_TOKENS` / `MAX_REFINED_QUERY_CHARS`. **NOT** touched:
`AGENT_TOOLS`, byte-exact literals, thresholds, routing table, audit-event schema, any `RULE_*`.

## Revision (2026-06-28, two-key authorized) — draft `<thinking>` scaffold REMOVED
Live breadth runs (real `ClaudeLLM` through the production gates) showed the **draft** `<thinking>`
scaffold suppresses inline `[chunk_id]` citations and tanks live grounding:
`redteam/LIVE_RUN_FINDINGS.stage10.md` = 25/100 grounded **with** the scaffold vs
`redteam/LIVE_RUN_FINDINGS.nothinking.md` = 40/50 grounded **without** it. The draft prompt now requests
inline citations + answer-only output; the dead `_DRAFT_THINKING_DIRECTIVE` constant was removed
(`CLAUDE.md` §8). Two draft-COT graded tests were retired under the two-key protocol (Asaf authorization
+ a pre-edit re-run confirming the *prompt* changed, not the test). **Retained:** the refine-query
`<thinking>` scaffold + strip, and the **defensive** `<thinking>` strip in `ClaudeLLM.draft` (the model
may still emit reasoning unasked).

## Definition of Done (QA §16) — verified
`QREF1` strip determinism (incl. nested-tag regression, added 2026-06-28); `QREF2` identity offline +
safe fallbacks; `QREF3` pipeline injects + audits the stage; `DRAFT-COT1` original question reaches the
draft prompt (defect regression); `DRAFT-COT2` `ClaudeLLM.draft` strips `<thinking>` before gate/export,
`MockLLM` never emits it. Determinism preserved: offline suite green, `make eval` metrics unchanged,
`make demo` clean. Numbers live in `FACTS.md`.
