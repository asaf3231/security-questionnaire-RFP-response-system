# PLAN.md — Reindeer RFP / Security-Questionnaire Response Agent

Project: **Comet** — the RFP/security-questionnaire response agent
Maintained by: Asaf

> This file is the live execution tracker. `CLAUDE.md` defines the rules. `QA_checklist.md` defines how
> each stage is verified. `FACTS.md` is the only home for numbers. `NOTES.md` records decisions + handback
> pointers. `STATE.md` is the resume checkpoint.

---

## How to use this file
- Work **one stage at a time**. Do not advance until the current stage's Definition of Done is satisfied.
- Read order for any session: `STATE.md` (the checkpoint, reconciled vs `git` + the live suite) →
  then, only if it's insufficient: `CLAUDE.md` → `PLAN.md` → `QA_checklist.md` → `FACTS.md` → `NOTES.md`.
- **Every DoD item references a check ID in `QA_checklist.md`.** A stage is done only when every
  referenced check **passes — verified by running it**, not by inspection.
- **Numbers live in `FACTS.md` only.** Status cells reference a verified fact by name; they never
  restate the literal value. Config constants live in `CLAUDE.md` §9 and are referenced by name.
- After each stage the executer's handback is written to `handbacks/stage-<N>.md` and only a **pointer
  line** is appended to `NOTES.md`. The **PM** updates the stage status after its own verification —
  never the executer — and overwrites `STATE.md`.

Status values: ⬜ Not started · 🔄 In progress · 🟡 Awaiting verification · ⚠️ Blocked · ✅ Complete

---

## Project shape (locked at genesis, 2026-06-27)
- **Deliverable:** a Python **service repo + CLI** (the running agent + an offline deterministic
  test/eval suite + scripts) **plus** a 1–2 page **Brief/Deck** and a **Technical Appendix**
  (`CLAUDE.md` §0.2). No notebook (the notebook discipline is re-expressed as the service workflow,
  `CLAUDE.md` §8). *(Asaf, four genesis forks — `NOTES.md` 2026-06-27.)*
- **Stack:** `rank_bm25` deterministic lexical retrieval + a 4-layer Agent Context Stack + Claude
  (`anthropic` SDK) **only** in the gated live draft lane; `MockLLM` is the offline graded path.
- **Confidence:** hybrid — a deterministic property-validator gate decides the number/routing; the LLM
  writes the rationale only.
- **Governance:** every boundary is a grep-enforceable `RULE_*` (`CLAUDE.md` §5) with a chokepoint,
  an audit reason-code, and a QA ID.
- **The build is staged so a runnable vertical slice — one questionnaire taken intake→export with both
  demo cases — exists by Stage 6**, leaving 7–9 for eval, hardening, and the written artifacts.

---

## Stage tracker

| Stage | Name | DoD checks (`QA_checklist.md`) | Reviewer gate | Status |
|---:|---|---|:---:|---|
| 0 | Project setup & spine | meta (this file set) | — | ✅ Complete (Asaf green-lit 2026-06-27) |
| 1 | Environment, secrets, config & synthetic inputs | `ENV1`–`ENV4`, `SEC1`–`SEC2`, `KB1`–`KB2`, `DATA1` | ✅ | ✅ Complete (2026-06-27; suite 39 green — see FACTS) |
| 2 | KB chunks + deterministic retrieval (`rank_bm25`) | `RET1`–`RET3` | ✅ | ✅ Complete (2026-06-27; suite 71 green; Recall@5 — see FACTS) |
| 3 | Context Stack + draft generation + grounding | `CTX1`–`CTX4`, `SCHEMA1`, `DRAFT1`–`DRAFT2`, `GROUND1` | ✅ | ✅ Complete (2026-06-27; suite 116/1-skip — see FACTS) |
| 4 | Confidence + routing + state machine | `CONF1`–`CONF3`, `ROUTE1`–`ROUTE3`, `STATUS1`–`STATUS2` | ✅ | ✅ Complete (2026-06-27; suite 179/1-skip — see FACTS) |
| 5 | Audit log + export + hard boundary | `AUDIT1`–`AUDIT3`, `EXPORT1`–`EXPORT3`, `BOUND1`–`BOUND2` | ✅ | ✅ Complete (2026-06-27; suite 232/1-skip — see FACTS) |
| 6 | End-to-end pipeline + the two demo cases | `PIPE1`–`PIPE2`, `DEMO1`–`DEMO2`, `RULE1`–`RULE2` | ✅ | ✅ Complete (2026-06-27; suite 278/1-skip — see FACTS) |
| 7 | Offline eval harness + Option-A routing + confidence refactor | `EVAL1`–`EVAL3`, `RET2`, `LEAK4`–`LEAK5` | ✅ | ✅ Complete via honest re-do **7r** (2026-06-27; first attempt 39469d0 REJECTED as fabricated → fixed; suite 315/1, eval-006 honestly caught — see FACTS) |
| 8 | Anti-leakage & packaging hardening | `LEAK1`–`LEAK-S`, `PKG1`–`PKG3`, `SEC1`–`SEC2`, `META-*` | ✅ (+sec-scan) | ✅ Complete (2026-06-27; suite 373/1; security scan CLEAN — see FACTS) |
| 9 | Brief/Deck + Technical Appendix | `DOC1`–`DOC2` | — | ✅ Complete (2026-06-28; `brief/REINDEER_BRIEF.md` + `appendix/TECHNICAL_APPENDIX.md`; every number → FACTS) |
| 10 | Intelligent Query Refinement (LLM query expansion; draft `<thinking>` scaffold removed 2026-06-28 per live evidence) | `QREF1`–`QREF3`, `DRAFT-COT1`–`DRAFT-COT2` | ✅ `/code-review` | ✅ Complete (2026-06-28; brief+handback authored, `/code-review` run — 1 finding FIXED; Asaf sign-off; suite — see FACTS) |

**Reviewer-gate trigger (this project):** on any stage that touches a **graded contract** — a §9
named constant, a tool/function signature, the `LLMProvider` interface, a `app/schema.py` Pydantic
model, any `RULE_*` identifier or its chokepoint, a byte-exact literal (`REVIEW_BANNER`,
`UNGROUNDED_PLACEHOLDER`), a confidence threshold, the routing table, or the audit-event schema — run
the native **`/code-review`** utility (`CLAUDE.md` §1.3). Pure-eval and the doc stage skip it (PM's own
QA suffices). **Stage 8** additionally runs the native **`/security-review`** utility as its
governance / anti-leakage gate. Executers are `general-purpose` subagents spawned cold per stage.

---

## Stage 0 — Project setup & spine
**Goal:** Create the spine and lock the architecture, stack, constants, literals, the `RULE_*`
governance registry, and the task-specific anti-leakage rule before any code.
**Inputs:** `Assignment.md`, `PM_Methodology_Prompt.md`, `ORCHESTRATION.md`, the read-only `Reference/`
quality bar.
**Outputs:** `CLAUDE.md`, `PLAN.md`, `QA_checklist.md`, `FACTS.md`, `STATE.md`, `NOTES.md`, `PM_LOG.md`.
**Definition of Done:**
- [x] `CLAUDE.md` created (env + pinned deps incl. `rank_bm25`; import-safety; synthetic-input
  compliance; the 8 agent functions; the `RULE_*` registry + chokepoints; the 4-layer Context Stack;
  the anti-leakage rule; the deterministic run workflow; §9 constants + byte-exact literals).
- [x] `QA_checklist.md` created (stable IDs `ENV/SEC/KB/DATA/RET/CTX/SCHEMA/DRAFT/GROUND/CONF/ROUTE/
  STATUS/AUDIT/EXPORT/BOUND/PIPE/DEMO/EVAL/LEAK/RULE/PKG/DOC`, each mapped to a stage).
- [x] `PLAN.md` created (this file); every stage DoD references QA check IDs.
- [x] `FACTS.md` created (ledger header + format; rows fill as stages verify).
- [x] `NOTES.md` + `STATE.md` created (genesis decisions, the four forks, codename, open questions).
- [x] **Asaf review** — **green-lit 2026-06-27** (architecture + spine APPROVED; OQ-1/OQ-2 resolved,
  codename confirmed — see `NOTES.md`). Spine committed as the `stage-0-spine` baseline on `main`.
**Status:** ✅ Complete — spine authored, cross-checked (all QA IDs resolve; 11 `RULE_*` each with 1
registry row + ≥1 QA mention; no stray literals; `Reference/` untouched), green-lit, and committed.
**Next action:** Stage 1 under the ORCHESTRATION.md loop (cold `general-purpose` executer → PM QA →
`/code-review` gate).

---

## Stage 1 — Environment, secrets, config & synthetic inputs
**Goal:** Stand up a clean, import-safe repo: pinned deps, `.env.example`/`.gitignore`, `Makefile`,
`README.md`, `app/config.py` (§9 constants + `RULE_*` strings + lazy `_get_claude()`), `app/schema.py`
(Pydantic models), and the validated synthetic `data/*` — before any agent logic.
**Inputs:** `CLAUDE.md` §1/§2/§4/§9; the chosen pins; the synthetic KB/questionnaire/policy design.
**Outputs:** `requirements.txt`, `.env.example`, `.gitignore`, `Makefile`, `README.md`,
`app/config.py`, `app/schema.py`, **`app/kb.py` (load + validate ONLY — ranking deferred to Stage 2)**,
`data/*.synthetic.*`, `tests/`.
> *Plan refinement 2026-06-27 (Asaf): KB1/DATA1 validation is enforced in Stage 1 — the load+validate
> half of `app/kb.py` lands here so data integrity is guaranteed **before** the Stage 2 retrieval
> logic. The `rank_bm25` ranking half of `app/kb.py`/`retrieval.py` stays in Stage 2.*
**Definition of Done (QA: `ENV1`–`ENV4`, `SEC1`–`SEC2`, `KB1`–`KB2`, `DATA1`):**
- [x] `ENV1`/`ENV2` — fresh venv installs; every third-party import pinned `==` (24 pins, see FACTS);
  `DRAFT_MODEL=claude-sonnet-4-6` pinned (`OQ-1` resolved).
- [x] `ENV3`/`ENV4` — `make test` clean offline (no `.env`); existing `app.*` modules import
  side-effect-free from a clean process (lazy `_claude_client` `None`); ENV4 proven progressively
  per stage (Stage 1: config/schema/kb).
- [x] `SEC1`/`SEC2` — no key/token in any tracked file or sample (PM-independent scan: zero real-key
  shapes); `.env` gitignored; `.env.example` placeholder only (`RULE_NO_SECRET`).
- [x] `KB1`/`DATA1` — KB/questionnaires/policy-tags validate on load (**strict explicit `ValueError`,
  not `KeyError`** — Asaf emphasis); only `approved==True` retrievable; routing map ⊆ `REVIEWER_QUEUES`.
- [x] `KB2` — no `data/*` value hardcoded in code/prompts (`LEAK3`).
**Reviewer gate:** ✅ `/code-review` run — 1 Important finding (premature stub modules, CLAUDE §8)
**fixed** via warm-agent correction; 2 minor `kb.py` findings deferred to Stage 2. SEC1 test was
modified during the fix (regex precision) — PM scrutinized under verifier-independence, re-verified
independently (no real secret masked), **accepted as a strengthening** (see `NOTES.md` D-S1).
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 39 green; committed as `stage-1-env` on `main`.

---

## Stage 2 — KB chunks + deterministic retrieval (`rank_bm25`)
**Goal:** Load the KB at the **paragraph / approved-answer chunk** level and implement deterministic
lexical retrieval via `rank_bm25` + a topic/sensitivity tag filter, tuned **Recall-first**.
**Inputs:** `CLAUDE.md` §3.1/§9 (`RETRIEVAL_TOP_K`, `BM25_K1`, `BM25_B`, `RECALL_AT_K_TARGET`); `app/kb.py`.
**Outputs:** `app/kb.py`, `app/retrieval.py`, `tests/`, labeled `fixtures/eval/` seed for Recall@K.
**Definition of Done (QA: `RET1`–`RET3`):**
- [x] `RET1` — `retrieve(question)` returns ≤ `RETRIEVAL_TOP_K` approved chunks via `rank_bm25`
  (BM25Okapi, config params); non-approved never returned; topic + `allowed_sensitivities` filters; no network.
- [x] `RET2` — **Recall@K** computed over `fixtures/eval/` by `rubric.py`, recorded in `FACTS.md`,
  meets `RECALL_AT_K_TARGET` (PM re-computed; perturb→0.0 proves computed, `RULE_NO_FABRICATED_METRIC`).
- [x] `RET3` — determinism: identical ranked `chunk_id` list across sequential runs (chunk_id tiebreak).
- [x] Deferred Stage-1 `kb.py` fixes cleared: dead `!= "approved"` condition removed; chunk_id-uniqueness `ValueError` added.
**Reviewer gate:** ✅ `/code-review` run — **APPROVE**, no correctness findings; 1 minor efficiency note
(`retrieve()` rebuilds the BM25 index per call) → deferred to Stage 6 pipeline (build index once). See NOTES.
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 71 green; committed as `stage-2-retrieval`.

---

## Stage 3 — Context Stack + draft generation + grounding
**Goal:** Assemble the 4-layer backpack and draft answers from it, with the byte-exact grounding gate;
offline `MockLLM` is the graded path, `ClaudeLLM` the gated live lane.
**Inputs:** `CLAUDE.md` §5 (`RULE_GROUNDED_ONLY`), §7, §9; `app/schema.py`; the retrieval output.
**Outputs:** `app/context_stack.py`, `app/llm.py`, `app/draft.py`, `tests/`.
**Definition of Done (QA: `CTX1`–`CTX4`, `SCHEMA1`, `DRAFT1`–`DRAFT2`, `GROUND1`):**
- [x] `CTX1`–`CTX4` — 4 layers present; Retrieval layer = ONLY passed chunks (`[chunk_id] text`);
  Constraint layer injects the high-risk clause for high-risk items; State layer = "Question X of Y".
- [x] `SCHEMA1` — `DraftAnswer`/`Citation` validate; empty-text draft rejected.
- [x] `DRAFT1` — `draft_answer(context_stack)` returns text + `citations[]`; offline `MockLLM`
  deterministic (PM re-verified identical output); prompt built only from the `ContextStack`.
- [x] `DRAFT2` — offline degradation verified (raising provider → `UNGROUNDED_PLACEHOLDER`, no
  exception); live half `@skipif(no key)` (1 skip).
- [x] `GROUND1` — ungrounded (no citation / fabricated id / low coverage) → `UNGROUNDED_PLACEHOLDER`
  (byte-exact, PM-verified) + `GROUNDING_FAIL` reason-code (`RULE_GROUNDED_ONLY`).
**Reviewer gate:** ✅ `/code-review` — **APPROVE**, no correctness findings. Note: grounding is
**lexical** coverage (not semantic) — known limitation, backstopped by the live lane + human review.
**NEW §9 constants added (Asaf-flagged, additions only):** `GROUNDING_COVERAGE_MIN=0.5`,
`GROUNDING_FAIL` reason-code — see `NOTES.md` D-S3.
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 116/1-skip; committed as `stage-3-draft`.

---

## Stage 4 — Confidence + routing + state machine
**Goal:** Compute the hybrid confidence (deterministic gate + LLM rationale), route the risky items via
the three triggers, and advance items through the state machine with the no-self-approve guard.
**Inputs:** `CLAUDE.md` §5 (`RULE_HITM_REVIEW_TRIGGER`, `RULE_NO_SELF_APPROVE`), §9 thresholds; the
draft + retrieval signals; the `policy_tags` routing map.
**Outputs:** `app/confidence.py`, `app/routing.py`, `app/state.py`, `tests/`.
**Definition of Done (QA: `CONF1`–`CONF3`, `ROUTE1`–`ROUTE3`, `STATUS1`–`STATUS2`):**
- [x] `CONF1`/`CONF2` — score from the 3 property validators only (pure `_compute_score`); PM-verified
  `_claude_client` stays `None` + score invariant to rationale.
- [x] `CONF3` — threshold banding from §9 (in-between → "review", conservative).
- [x] `ROUTE1`–`ROUTE3` — high-risk / ambiguity / low-confidence each route with the correct
  reason-code; queue from the policy map / `DEFAULT_REVIEWER_QUEUE`; benign item → not routed.
- [x] `STATUS1` — only legal `ITEM_STATES` edges; illegal → `InvalidTransition`.
- [x] `STATUS2` — agent self-approve raises `SelfApproveBlocked` (`SELF_APPROVE_BLOCKED`,
  `RULE_NO_SELF_APPROVE`); `actor="human"` allowed. PM-verified.
**Reviewer gate:** ✅ `/code-review` — **APPROVE**. Minor (deferred to Stage 7): coverage/dominance
calc duplicated in the `confidence.py` rationale builder. **NEW §9 constants (Asaf-flagged):**
`DEFAULT_REVIEWER_QUEUE`, `ROUTED_HIGH_RISK`/`ROUTED_AMBIGUOUS`/`ROUTED_LOW_CONFIDENCE`/
`SELF_APPROVE_BLOCKED` — see `NOTES.md` D-S4. **Stage-6 note:** `case_confident-i3` routes (security tag).
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 179/1-skip; committed as `stage-4-routing`.

---

## Stage 5 — Audit log + export + hard boundary
**Goal:** Append-only JSONL audit (one event per transition + tool call), the local-disk-only export
with the sensitivity gate and review banner, and the no-external-send hard boundary.
**Inputs:** `CLAUDE.md` §5 (`RULE_NO_EXTERNAL_SEND`, `RULE_SENSITIVITY_GATE`, `RULE_AUDIT_COMPLETE`),
§7, §9; the state machine.
**Outputs:** `app/audit.py`, `app/export.py`, `tests/`.
**Definition of Done (QA: `AUDIT1`–`AUDIT3`, `EXPORT1`–`EXPORT3`, `BOUND1`–`BOUND2`):**
- [x] `AUDIT1`–`AUDIT3` — append-only JSONL, one line per `write_audit`; lines parse back to
  `AuditEvent`; redaction scrubs secret/email/phone (PM-verified placeholders present, raw gone).
- [x] `EXPORT1`–`EXPORT3` — APPROVED-only Markdown+CSV to local disk; sensitivity gate holds
  `internal`/`restricted` unless `review_approved` (PM-verified); `REVIEW_BANNER` byte-exact atop
  non-approved previews.
- [x] `BOUND1`/`BOUND2` — PM AST-grep: `export.py` imports only `__future__/app/csv/io/pathlib`
  (zero network primitives); affirmative `RULE_NO_EXTERNAL_SEND` audit; non-APPROVED never exported.
- [x] Import-safety re-verified: a clean import of all 14 modules creates **no** `audit/`/`exports/` dir.
**Reviewer gate:** ✅ `/code-review` — **APPROVE**, no correctness findings. **NEW (additive, Asaf-flagged):**
schema `ResponseDocItem.sensitivities`+`review_approved`; §9 reason-codes `SENSITIVITY_HOLD`,
`EXTERNAL_SEND_BLOCKED` (synced) — see `NOTES.md` D-S5.
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 232/1-skip; committed as `stage-5-export`.

---

## Stage 6 — End-to-end pipeline + the two demo cases
**Goal:** Wire the full pipeline and ship the two assignment-mandated demo cases as runnable `make demo`
outputs; prove safe-terminal and full `RULE_*` coverage.
**Inputs:** all Stage 1–5 modules; `data/questionnaires/case_confident` + `case_review`.
**Outputs:** `app/pipeline.py`, `scripts/run_demo.py`, `scripts/run_live_draft.py`, `tests/`.
**Definition of Done (QA: `PIPE1`–`PIPE2`, `DEMO1`–`DEMO2`, `RULE1`–`RULE2`):**
- [x] `PIPE1` — full happy path → `ResponseDoc`, deterministic under `MockLLM`; audited per transition.
- [x] `PIPE2` — injected retriever/provider failure → all items `ROUTED_FOR_REVIEW` + `ERROR_TERMINAL`;
  **no uncaught exception** (PM-verified by injection). `RULE_SAFE_TERMINAL`.
- [x] `DEMO1` — `case_confident`: i1 (public) confident→human-approved→exported; i2 (internal) confident
  but held by sensitivity; i3 (restricted+security) `ROUTED_HIGH_RISK→security` (defense-in-depth showcase).
- [x] `DEMO2` — `case_review`: both items `ROUTED_HIGH_RISK→legal`; `REVIEW_BANNER` in preview; **not exported**.
- [x] `RULE1`/`RULE2` — every `RULE_*` greps to its chokepoint + emits its reason-code in the audit (PM-verified).
- [x] Retrieval refactored to full-corpus `Retriever` (built once); RET1–3 untouched + green; Recall@K held 1.0.
**Reviewer gate:** ✅ `/code-review` — **APPROVE**, no correctness findings. **Open design question → Asaf:**
internal/restricted sensitivity is an export gate but not a routing trigger (i2 "stuck" + dropped from demo
summary) — decide route-vs-gate (NOTES D-S6). `make demo` needs venv active (Stage-8 packaging). `ERROR_TERMINAL`
added+synced to §9.
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 278/1-skip; committed as `stage-6-pipeline`.

---

## Stage 7 — Offline evaluation harness
**Goal:** A deterministic eval over labeled held-out fixtures: Recall@K, grounding rate, routing
accuracy, confidence calibration — every number computed, none fabricated, no contamination.
**Inputs:** `CLAUDE.md` §5 (`RULE_NO_EVAL_CONTAMINATION`, `RULE_NO_FABRICATED_METRIC`); `fixtures/eval/`.
**Outputs:** `app/eval/harness.py`, `app/eval/rubric.py`, `app/eval/fixtures.py`, `tests/`; `make eval`.
**Definition of Done (QA: `EVAL1`–`EVAL3`, `RET2`, `LEAK4`–`LEAK5`):**
- [x] `EVAL1` — recall@k + grounding_rate + routing_accuracy + calibration all computed from held-out
  labeled fixtures (PM re-ran `make eval`); recorded in `FACTS.md`.
- [x] `EVAL2` — held-out split proven; contamination injection raises (`RULE_NO_EVAL_CONTAMINATION`);
  `run_eval` does not mutate `data/kb/*`.
- [x] `EVAL3` — calibration matrix computed over the held-out set (auto/review × grounded/ungrounded).
- [x] `LEAK4`/`LEAK5` — contamination + fabricated-metric (perturb→changes) cross-checks green.
- [x] **Option A** (Asaf): internal/restricted sensitivity → `compliance` queue (`ROUTED_SENSITIVE`,
  4th/lowest trigger) — PM-verified i2 now routes to compliance (unblocked); §9 + §5.1 synced.
- [x] **Confidence refactor**: rationale reuses pre-computed components; **score VALUE unchanged**
  (PM-verified i1/i2/i3 = 0.799/0.861/0.880, identical to Stage 6); CONF1–3 green.
- [x] **GOV-FAIL-S7 → 7r honest re-do:** first attempt (39469d0) REJECTED by Asaf as fabricated
  (`_simulate_grounding` tautology + eval-006 gold fitted to a confidence bug). Fixed via structural
  code: single-chunk `retrieval_dominance` bounded by coverage; grounding question-relevance
  (`GROUNDING_QUESTION_COVERAGE_MIN`); harness wired to REAL `grounding_check`; eval-006 gold reverted
  to the negative intent. **PM ran the REAL pipeline on eval-006 → grounded=False · score 0.074 ·
  ROUTED_LOW_CONFIDENCE (code-driven, not gold-fitted); perturb proof confirms metrics computed.**
**Reviewer gate:** ✅ `/code-review` — **APPROVE** (routing + confidence + grounding are graded
contracts). Eval harness at spine path `app/eval/harness.py` (Asaf wrote `app/eval_harness.py` —
flagged). Verifier-independence re-verified: test_stage1–6 untouched; only eval-006 gold + the one
calibration test changed (reflecting the honest fix); no removed/weakened asserts.
**Status:** ✅ Complete (honest 7r) — PM-verified 2026-06-27; suite 315/1-skip; committed as the
honest `stage-7-eval`.

---

## Stage 8 — Anti-leakage & packaging hardening
**Goal:** Prove all seven leakage protections, harden packaging for a clean-checkout run, and pass the
governance gate.
**Inputs:** `CLAUDE.md` §5.2 (the seven `LEAK*`); the whole tree.
**Outputs:** hardened `.gitignore`/`README.md`/docstrings; redacted sample export+audit; `tests/`.
**Definition of Done (QA: `LEAK1`–`LEAK-S`, `PKG1`–`PKG3`, `SEC1`–`SEC2`, `META-*`):**
- [x] `LEAK1`–`LEAK-S` — all seven leakage cross-checks green (PM re-verified across the full tracked set).
- [x] `PKG1`–`PKG3` — venv-clean Makefile (`make test` 373/1 with NO manual `source`); `.gitignore`
  correct; pyproject package boundary (tests/fixtures/data excluded); README run-from-clean section;
  redacted samples tracked under `samples/`.
- [x] `META-*` — META-LOCK (add-only honored: tests/fixtures unmodified), META-FALSIFY/REALPATH
  (no `_simulate_*`, red negative case), META-PROVENANCE (`fixtures/eval/PROVENANCE.md` added).
- [x] **Security review** — native `/security-review` CLI cannot run (no git remote/`origin`); PM ran the
  equivalent comprehensive governance scan → **CLEAN, no findings** (no real secret/PII; `.env` ignored;
  no network-send primitive outside the gated `app/llm.py`; samples redacted).
**Reviewer gate:** ✅ manual security/governance scan (CLEAN). *(Native `/security-review` needs a remote
— offer to push if Asaf wants the CLI run.)*
**Status:** ✅ Complete — PM-verified 2026-06-27; suite 373/1; committed as `stage-8-packaging`.

---

## Stage 9 — Brief/Deck + Technical Appendix
**Goal:** Author the two written deliverables, every number grounded in `FACTS.md`.
**Inputs:** the shipped repo; `FACTS.md`; `Assignment.md` evaluation rubric.
**Outputs:** `brief/REINDEER_BRIEF.md`, `appendix/TECHNICAL_APPENDIX.md`.
**Definition of Done (QA: `DOC1`–`DOC2`):**
- [x] `DOC1` — `brief/REINDEER_BRIEF.md`: workflow, architecture, assumptions, success metrics; every
  number references `FACTS.md` (incl. the honest live-grounding limitation).
- [x] `DOC2` — `appendix/TECHNICAL_APPENDIX.md`: pipeline/module map, schema, prompt/tool design,
  guardrails (`RULE_*`), state machine, routing precedence, audit/logging — consistent with shipped code.
**Reviewer gate:** — (docs; PM verified numbers against `FACTS.md`).
**Status:** ✅ Complete — authored 2026-06-28; numbers trace to `FACTS.md`.

---

## Stage 10 — Intelligent Query Refinement (Asaf architectural directive, 2026-06-27)
**Goal:** Add an LLM **QUERY_REFINEMENT** stage before retrieval (raw question → optimized search query
via synonym/technical expansion), route the **original** question into the draft prompt (fixing a defect
where it never reached the model), and scaffold the live Refinement + Draft prompts with `<thinking>`
reasoning that code deterministically strips before any gate/export sees it.
**Inputs:** `CLAUDE.md` §5/§8/§9; the live-lane flow; `redteam/LIVE_RUN_FINDINGS.md` baseline.
**Outputs:** NEW `app/query_optimizer.py`; additive edits to `app/schema.py` (`ContextStack.question`),
`app/llm.py` (`LLMProvider.refine_query` identity default + `ClaudeLLM` override + `<thinking>` strip +
QUESTION block), `app/context_stack.py`, `app/pipeline.py` (refine + audit before retrieve),
`scripts/run_live_draft.py`; NEW `tests/test_stage10_query_refinement.py` (27 tests at landing; 31 after the
2026-06-28 cleanup — 1 COT test retired, 5 added). Brief: `briefs/stage-10.md`; handback: `handbacks/stage-10.md`.
**Definition of Done (QA: `QREF1`–`QREF3`, `DRAFT-COT1`–`DRAFT-COT2`):**
- [x] `QREF1` — `strip_thinking_block` deterministic & total (well-formed / dangling / multiple / case /
  **nested / token-fusion** added 2026-06-28; now a depth-aware scan, nested-safe).
- [x] `QREF2` — `refine_query` identity offline (MockLLM ⇒ determinism preserved) + safe fallbacks
  (empty / thinking-only / non-alphanumeric / exception / runaway length → original question).
- [x] `QREF3` — pipeline injects + audits the stage (`refine_query` event, `original`/`optimized`, `to_state` set).
- [x] `DRAFT-COT1` — original question reaches the draft prompt (defect regression green); backward-compatible.
- [x] `DRAFT-COT2` — `ClaudeLLM.draft` defensively strips `<thinking>` before gate/export (real path, only
  client faked); MockLLM never emits `<thinking>`.
- [x] **Determinism preserved:** full offline suite green (see FACTS), **0 offline regressions**;
  `make eval` metrics unchanged; `make demo` clean; add-only honored except the authorized two-key COT retirement.
**Revision (2026-06-28, two-key authorized — draft `<thinking>` scaffold REMOVED):** live evidence
(`redteam/LIVE_RUN_FINDINGS.stage10.md` 25/100 grounded WITH vs `.nothinking.md` 40/50 WITHOUT) showed the
draft scaffold suppressed inline citations and tanked live grounding. The draft prompt now requests inline
`[chunk_id]` citations + answer-only; the dead `_DRAFT_THINKING_DIRECTIVE` constant was removed (§8); two
draft-COT tests were retired under the two-key protocol (Asaf authorization + a pre-edit re-run proving the
*prompt* changed). The refine-query `<thinking>` scaffold + the defensive draft-strip are retained.
**Graded contracts touched (additive, Asaf-directed):** `LLMProvider` interface, `ContextStack` schema,
`app/pipeline.py` chokepoint, the `_build_prompt`/`draft` prompt+strip path, two new §9 constants
(`REFINE_MAX_TOKENS`, `MAX_REFINED_QUERY_CHARS`). **NOT** touched: `AGENT_TOOLS`, byte-exact literals,
thresholds, routing table, audit-event schema, any `RULE_*`.
**Caveat (recorded):** the in-`<thinking>` self-checks were always defense-in-depth UX, **not** enforcement —
the code chokepoints remain the governance (CLAUDE.md §5).
**Reviewer gate:** ✅ `/code-review` (contract-touching) run 2026-06-28 — 1 finding (token-fusion in the
rewritten strip) **FIXED** + regression test added; 1 low finding (CLAUDE §9 constants) addressed. **QA IDs:**
`QREF1`–`QREF3`, `DRAFT-COT1`–`DRAFT-COT2` (QA §16).
**Status:** ✅ Complete — PM-verified + `/code-review` + Asaf sign-off 2026-06-28; committed on
`redteam/crazy-testing` (FACTS suite row carries the sha).

---

## Open questions (resolved — full text in `NOTES.md`)
- **OQ-1** ✅ RESOLVED — `DRAFT_MODEL` = `claude-sonnet-4-6` (Asaf 2026-06-27). Already the §9 default.
- **OQ-2** ✅ RESOLVED — export **both** Markdown (`exports/*.md`) and CSV grid (`exports/*.csv`) at
  Stage 5 (`EXPORT1`); Asaf 2026-06-27.
