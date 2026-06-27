# QA_checklist.md — Test-Driven-Development Blueprint

Project: **Reindeer RFP / Security-Questionnaire Response Agent ("Comet")**
Maintained by: Asaf

> This file is the verification contract. `CLAUDE.md` defines the rules, `PLAN.md` tracks the stages,
> `NOTES.md` records decisions. **The pass/fail counts and metric values these checks produce live in
> `FACTS.md`** (the Verified-Facts Ledger) — reference them there, never restate the literal here.
> **Every stage in `PLAN.md` lists the check IDs below as its Definition of Done.** A stage is not
> "done" until its referenced checks pass — *run, not inspected*. Checks are written **before** the
> matching code (test-first). Each has a stable ID (e.g. `GROUND1`, `ROUTE2`, `BOUND1`) so `PLAN.md`
> can reference it without ambiguity.
>
> **Live vs offline:** the default suite (`make test`) is **offline, deterministic, network-free, and
> places no Claude call**. Checks marked **(live, gated)** require `ANTHROPIC_API_KEY`; they are
> `@pytest.mark.skipif`-gated and **SKIPPED (not failed)** when the key is absent. `make demo-live` is
> the only path that exercises them.
>
> **Constant-source rule:** every threshold/literal a check asserts (`CONFIDENCE_*`, `RETRIEVAL_TOP_K`,
> `AMBIGUITY_SCORE_MARGIN`, `REVIEW_BANNER`, `UNGROUNDED_PLACEHOLDER`, the `RULE_*` strings) is imported
> from `app/config.py` (§9) — a test never re-types the literal value.

---

## §0. Harness, environment & fixtures (`ENV*`)

| ID | Check | Method | Pass condition |
|---|---|---|---|
| `ENV1` | Fresh-venv install | `python -m venv .venv && pip install -r requirements.txt` | Exit 0; all pins resolve |
| `ENV2` | Every import is pinned | AST-scan every non-stdlib import in `app/`+`scripts/`; assert each appears in `requirements.txt` with `==` | No imported third-party module unpinned (incl. `rank_bm25`, `anthropic`, `pydantic`) |
| `ENV3` | One-command clean run | `make test` from a fresh checkout with **no `.env`** | Suite green; **no network, no Claude client built, no call** |
| `ENV4` | **Import-safety** | `python -c "import <the app.* modules that EXIST at the current stage>"` from an empty dir, no `.env`, no network. Modules are created as their stage lands (no premature stubs, §8), so the set grows per stage — **Stage 1: `app.config, app.schema, app.kb`**; the full 13-module set is re-proven as later modules land | Exit 0; **zero** side effects (no client, no `.env` read, no `data/*` read, no file written); lazy singletons `None`. The single most important environment check |

**Shared fixtures**
- `tmp_kb` — a small schema-valid `approved_answers.synthetic.json` (≥1 `public`, ≥1 `internal`/`restricted`, ≥1 `approved=False` non-retrievable, mixed `topic_tags`).
- `tmp_questionnaire` — a valid questionnaire with ≥1 confident-coverage item and ≥1 high-risk/low-coverage item.
- `tmp_policy_tags` — `SENSITIVITY_TAGS`, `HIGH_RISK_TAGS`, and the tag→queue routing map.
- `MockLLM` — the seeded (`RANDOM_SEED`), deterministic `LLMProvider`; returns a scripted draft + rationale from the assembled context; **never networks**; can be set to raise (live-lane error path).
- `gold_fixtures` — labeled eval gold under `fixtures/eval/` with the **held-out** questionnaire/KB split (`RULE_NO_EVAL_CONTAMINATION`).
- `frozen_clock` — deterministic timestamps so audit events are reproducible.

---

## §1. Secrets (`SEC*`) — `RULE_NO_SECRET`

| ID | Check | Pass condition |
|---|---|---|
| `SEC1` | No secret in any tracked file | grep the **git-true tracked set** (`git ls-files --cached --others --exclude-standard`) for `ANTHROPIC_API_KEY=` values, `sk-ant-` token prefixes, and any bearer token → zero hits; `.env` is gitignored (`git check-ignore .env`); `.env.example` holds placeholders only |
| `SEC2` | No secret in generated artifacts | grep `exports/`, `audit/`, and any tracked sample for a key/token → zero hits (`RULE_NO_SECRET` cross-check on outputs, not just source) |

---

## §2. Synthetic inputs (`KB*`, `DATA1`) — `RULE_NO_REAL_PII`

| ID | Check | Pass condition |
|---|---|---|
| `KB1` | KB validates on load | `data/kb/approved_answers.synthetic.json` parsed by name; required `chunk_id`/`answer`/`sensitivity` present; `sensitivity ∈ SENSITIVITY_TAGS`; a missing/renamed field → clean explicit `ValueError`, not a later `KeyError`; only `approved==True` chunks are retrievable |
| `DATA1` | Questionnaire + policy-tags validate on load | `data/questionnaires/*.synthetic.json` and `data/policy_tags.synthetic.json` load and validate (`questionnaire_id`, `items[].item_id`, `items[].question`; routing map references only `REVIEWER_QUEUES`) |
| `KB2` | No hardcoded input values | grep: no KB answer text, question literal, source name, or routing-map value appears in `app/` code or any prompt template (`LEAK3` cross-check) |

---

## §3. Retrieval (`RET*`) — `rank_bm25`, Recall-first

| ID | Check | Pass condition |
|---|---|---|
| `RET1` | Lexical retrieval + tag filter | `retrieve(question)` returns ≤ `RETRIEVAL_TOP_K` chunks scored by `rank_bm25` (params `BM25_K1`/`BM25_B`); only `approved==True` chunks; topic/sensitivity tag filter applied; non-`anthropic` import path = no network |
| `RET2` | **Recall@K on labeled fixtures** | over `gold_fixtures`, the labeled relevant chunk(s) appear in the top-`RETRIEVAL_TOP_K` at a rate **computed** by `app/eval/rubric.py`; the measured value is recorded in `FACTS.md` and meets `RECALL_AT_K_TARGET` (target lives in §9, measured value in `FACTS.md`) |
| `RET3` | Determinism | same query + same KB ⇒ identical ranked `chunk_id` list across runs (no set/dict ordering nondeterminism; `rank_bm25` is deterministic) |

---

## §4. Agent Context Stack — the "backpack" (`CTX*`)

| ID | Check | Pass condition |
|---|---|---|
| `CTX1` | Four layers present + nothing extraneous | `assemble_context(item, chunks)` returns a `ContextStack` with **all four** layers (Instruction / Retrieval / Constraint / State); the **Retrieval layer contains ONLY the retrieved chunk texts** — no KB content, no other item, nothing outside the top-K reaches the model (anti-dilution + grounding) |
| `CTX2` | Instruction layer | the Instruction layer carries the explicit RFP/questionnaire handling rules (from config/persona), not free text inlined elsewhere |
| `CTX3` | Constraint layer (hard boundaries as rules) | the Constraint layer injects the active hard boundaries (e.g. "do not answer legal-exposure questions without an approved doc"); a high-risk item carries the corresponding constraint string |
| `CTX4` | State layer | the State layer carries the position in the questionnaire (item *X* of *Y*) and the item's current `ITEM_STATES` value |

---

## §5. Schema, drafting & grounding (`SCHEMA*`, `DRAFT*`, `GROUND1`) — `RULE_GROUNDED_ONLY`

| ID | Check | Pass condition |
|---|---|---|
| `SCHEMA1` | Structured output models | `app/schema.py` Pydantic models (`DraftAnswer`, `Citation`, `ConfidenceResult`, `RoutingDecision`, `AuditEvent`, `ResponseDoc`) validate; a malformed draft (e.g. missing `citations`) is rejected at the boundary, not silently accepted |
| `DRAFT1` | Draft via the backpack | `draft_answer(context_stack)` produces a `DraftAnswer` with `text` + `citations[]` of retrieved `chunk_id`s; offline path uses `MockLLM` (deterministic); the prompt is built only from the `ContextStack` |
| `DRAFT2` | Live-lane error degrades safely (live, gated) | with `MockLLM` set to raise (and, gated, a real `ClaudeLLM` timeout), `draft_answer` returns a structured routed-for-review result with `UNGROUNDED_PLACEHOLDER`, never a partial/invented answer or an uncaught exception |
| `GROUND1` | **Grounding gate, byte-exact placeholder** | `grounding_check` rejects an answer whose claims are not covered by ≥ `GROUNDING_MIN_CITATIONS` retrieved chunks → substitutes `UNGROUNDED_PLACEHOLDER` (byte-exact) and routes; emits `RULE_GROUNDED_ONLY` / `GROUNDING_FAIL` to the audit log |

---

## §6. Confidence (`CONF*`) — hybrid: property validators + LLM rationale

| ID | Check | Pass condition |
|---|---|---|
| `CONF1` | Deterministic score | `score_confidence(retrieval, grounding)` returns a number derived **only** from property validators (retrieval top-score, question coverage, grounding ratio) — no model call decides the number; identical inputs ⇒ identical score |
| `CONF2` | LLM supplies rationale only | the `ConfidenceResult.rationale` string may come from the LLM, but removing/replacing it does **not** change the numeric `score` or the routing decision (rationale is explanatory, not authoritative) |
| `CONF3` | Threshold banding | `score >= CONFIDENCE_AUTO_THRESHOLD` ⇒ auto-draft band; `score < CONFIDENCE_REVIEW_THRESHOLD` ⇒ review band; in-between ⇒ review (conservative); bands read from §9 constants |

---

## §7. Routing & state machine (`ROUTE*`, `STATUS*`) — `RULE_HITM_REVIEW_TRIGGER`, `RULE_NO_SELF_APPROVE`

| ID | Check | Pass condition |
|---|---|---|
| `ROUTE1` | High-risk tag → route | an item carrying a `HIGH_RISK_TAGS` tag is routed to the mapped queue with reason-code `ROUTED_HIGH_RISK`, regardless of confidence |
| `ROUTE2` | Ambiguity → route | when top1−top2 BM25 score gap < `AMBIGUITY_SCORE_MARGIN` (or conflicting chunks), the item routes with `ROUTED_AMBIGUOUS` |
| `ROUTE3` | Low confidence → route + correct queue | `score < CONFIDENCE_REVIEW_THRESHOLD` routes with `ROUTED_LOW_CONFIDENCE`; the queue is resolved from `policy_tags` routing map (Security/Legal/Engineering/GTM), not hardcoded |
| `STATUS1` | State machine legality | items advance only along legal `ITEM_STATES` edges; an illegal transition raises a structured error, not a silent jump |
| `STATUS2` | **No self-approve** | no agent/code path transitions an item to `APPROVED` or `EXPORTED`; only an explicit human action does. An attempted agent self-approve is blocked and emits `RULE_NO_SELF_APPROVE` / `SELF_APPROVE_BLOCKED` (spy: the transition guard refuses) |

---

## §8. Audit, export & the hard boundary (`AUDIT*`, `EXPORT*`, `BOUND*`)

| ID | Check | Pass condition |
|---|---|---|
| `AUDIT1` | One event per transition + tool call | every state transition and every tool call appends exactly one JSONL audit event (`RULE_AUDIT_COMPLETE`); no silent gap across a full pipeline run (event count == transitions + tool calls) |
| `AUDIT2` | Event schema | each event has `timestamp`, `questionnaire_id`, `item_id`, `event`, `from_state`/`to_state`, `rule`, `detail`; validates against the `AuditEvent` model; append-only (no in-place edit) |
| `AUDIT3` | Audit redaction | no audit event contains a secret, a raw key, or unredacted real PII (`RULE_NO_SECRET`/`RULE_NO_REAL_PII` cross-check on the log) |
| `EXPORT1` | Export only APPROVED, local disk (Markdown + CSV) | `export_response` writes **both** a Markdown response doc (`exports/*.md`) and a CSV grid (`exports/*.csv`, one row per item: question/status/confidence/queue/citations) for **`APPROVED` items only**; a non-approved item is excluded; files are local (path under repo/`os.getcwd()`) |
| `EXPORT2` | **Sensitivity gate** | a chunk/answer tagged `internal`/`restricted` is excluded from the export unless its item reached `REVIEW_APPROVED`; otherwise held with `RULE_SENSITIVITY_GATE` / `SENSITIVITY_HOLD` (`LEAK-S`) |
| `EXPORT3` | Review banner byte-exact | any non-approved item rendered for human view carries `REVIEW_BANNER` byte-for-byte |
| `BOUND1` | **No external send** | static + runtime check: **no** code path imports/uses a network-send primitive (smtp/http POST/upload) outside `app/llm.py`'s gated Claude call; `export` emits `RULE_NO_EXTERNAL_SEND` to the audit log; a spy proves no send is attempted |
| `BOUND2` | Approval precedes export | `export_response` is unreachable for an item that has not passed a human `APPROVED` transition (`RULE_NO_SELF_APPROVE` cross-check) |

---

## §9. End-to-end pipeline & demo cases (`PIPE*`, `DEMO*`)

| ID | Check | Pass condition |
|---|---|---|
| `PIPE1` | Full happy path | `pipeline.run(questionnaire)` carries every item intake→retrieve→assemble→draft→score→route→status→audit; produces a `ResponseDoc`; deterministic under `MockLLM` |
| `PIPE2` | **Safe terminal** | an injected component failure (malformed chunk, empty retrieval, `MockLLM` raise) yields a routed-for-review item + `ERROR_TERMINAL` audit event — **no uncaught exception** anywhere in `pipeline.py` (`RULE_SAFE_TERMINAL`) |
| `DEMO1` | Confident auto-draft | `case_confident` → high confidence, grounded draft, **no** routing trigger; item sits as a confident draft awaiting human `APPROVED`; no `RULE_HITM_REVIEW_TRIGGER` fired |
| `DEMO2` | Human-review exception | `case_review` → a `RULE_HITM_REVIEW_TRIGGER` fires; item is `ROUTED_FOR_REVIEW` to the correct queue with `REVIEW_BANNER`; never auto-included in the export |

---

## §10. Offline evaluation (`EVAL*`) — `RULE_NO_FABRICATED_METRIC`, `RULE_NO_EVAL_CONTAMINATION`

| ID | Check | Pass condition |
|---|---|---|
| `EVAL1` | Every metric computed | `app/eval/rubric.py` computes Recall@K, grounding rate, routing accuracy, and confidence calibration **from labeled fixtures**; no test/eval hardcodes a score/confidence/approval; the values are recorded in `FACTS.md` |
| `EVAL2` | **No contamination** | the harness proves the questionnaire-under-test is **held out** of the KB it is answered from (the gold answer is not retrievable as its own evidence); a deliberate contamination attempt is detected and fails the check (`RULE_NO_EVAL_CONTAMINATION`) |
| `EVAL3` | Calibration is real | confidence calibration (auto-band items vs. graded-correct) is computed over the held-out set, not asserted; the figure lives in `FACTS.md` |

---

## §11. Anti-leakage cross-checks (`LEAK*`)

| ID | Check | Pass condition |
|---|---|---|
| `LEAK1` | Secret leakage | = `SEC1`/`SEC2` over the full tracked set + outputs → zero hits (`RULE_NO_SECRET`) |
| `LEAK2` | PII / customer-data leakage | only `*.synthetic.*` KB/questionnaire fixtures are tracked; grep for real-looking emails/phones/customer names in tracked data → zero (`RULE_NO_REAL_PII`) |
| `LEAK3` | Hardcoded-input leakage | = `KB2`: no `data/*` value inlined in `app/`/prompts |
| `LEAK4` | Eval contamination | = `EVAL2` (`RULE_NO_EVAL_CONTAMINATION`) |
| `LEAK5` | Fabricated-metric leakage | = `EVAL1`: every reported number traces to a computing function over labeled input (`RULE_NO_FABRICATED_METRIC`) |
| `LEAK-G` | Grounding leakage | = `GROUND1`: no asserted answer without a cited retrieved chunk (`RULE_GROUNDED_ONLY`) |
| `LEAK-S` | Sensitivity-tag leakage | = `EXPORT2`: no `internal`/`restricted` content exported without human review (`RULE_SENSITIVITY_GATE`) |

---

## §12. `RULE_*` registry coverage (`RULE*`) — the meta-gate

| ID | Check | Pass condition |
|---|---|---|
| `RULE1` | Every rule has a chokepoint | for each `RULE_*` string in `app/config.py` §9, grep proves it is referenced at the chokepoint module named in `CLAUDE.md` §5.1 — **no orphan rule** (a defined `RULE_*` with no enforcement site fails) |
| `RULE2` | Every fired rule is audited | a pipeline run that triggers each `RULE_*` writes its reason-code to the audit log (e.g. `GROUNDING_FAIL`, `ROUTED_LOW_CONFIDENCE`, `SELF_APPROVE_BLOCKED`, `SENSITIVITY_HOLD`, `EXTERNAL_SEND_BLOCKED`, `ERROR_TERMINAL`); reason-codes match §5.1 |

---

## §13. Packaging (`PKG*`)

| ID | Check | Pass condition |
|---|---|---|
| `PKG1` | Clean-checkout reproduction | from a fresh clone: `venv → pip install -r requirements.txt → make test → make demo` all succeed with no manual fixups (`ENV1`–`ENV4` umbrella) |
| `PKG2` | `.gitignore` correctness | `.env`, `exports/`, `audit/`, `.venv`, real/customer data are gitignored (`git check-ignore` each); one redacted sample export + audit may be tracked |
| `PKG3` | README run-from-clean | `README.md` documents the exact one-command path (§1) and the `make demo` / `make demo-live` distinction; each `app/` module has a top docstring stating its responsibility + any `RULE_*` it enforces |

---

## §14. Written deliverables (`DOC*`)

| ID | Check | Pass condition |
|---|---|---|
| `DOC1` | Brief/Deck grounded in FACTS | `brief/REINDEER_BRIEF.md` covers workflow, architecture, assumptions, success metrics; **every number references a `FACTS.md` row** (no restated literal) |
| `DOC2` | Technical Appendix complete | `appendix/TECHNICAL_APPENDIX.md` covers prompt/tool design, the data schema, the guardrails (`RULE_*` registry), state changes, reviewer routing, and audit/logging; matches the shipped code (names/IDs consistent) |

---

## §15. Governance-tier meta-gates (`META-*`) — `RULE_GRADED_ARTIFACT_LOCK`, `RULE_METRIC_FALSIFIABLE`

> Process integrity, **not** pipeline behavior: these guard the verification itself against gaming
> (gold-fitting, internal-gate simulation, tautological metrics). **General to any project.** Full
> principles in `PM_Methodology_Prompt.md` → *Metric Integrity & Anti-Gaming* (#4–#7); registry rows in
> `CLAUDE.md` §5.3. Run as a `make test` / `make eval` pre-flight **and** at every stage handback.

| ID | Check | Pass condition |
|---|---|---|
| `META-LOCK` | **Graded-artifact set is locked** | `scripts/check_graded_artifacts.sh` scans the git diff of the locked set (`tests/`, `fixtures/`, eval gold / answer keys, expected-output snapshots) vs `HEAD`: **added** files pass; any **modified/deleted** line in an existing tracked artifact **aborts** `make test`/`make eval` non-zero unless the human override `ALLOW_GRADED_EDIT=1` is set. A failing test is a **finding**, never fixed by editing the test (`RULE_GRADED_ARTIFACT_LOCK`) |
| `META-FALSIFY` | **Every metric/gate is falsifiable** | each metric/gate has ≥1 **"red" negative fixture** it is *required* to score as failing/routing/rejecting; running it on that fixture reports failure. A metric that cannot report failure (a tautology) fails this check; a suite/eval with **no negative cases is treated as unverified** (`RULE_METRIC_FALSIFIABLE`; Metric Integrity #4) |
| `META-REALPATH` | **Eval runs the real internal path** | the eval/test imports and exercises the system's **real** internal gates (grounding/scoring/routing/validation); only non-deterministic **external** boundaries (network/clock/model/RNG) are substituted, and only with **behavior-faithful, non-constant** fakes. A `_simulate_*`/shortcut that hard-codes an internal gate's verdict **fails** this check (`RULE_METRIC_FALSIFIABLE`; Metric Integrity #6) |
| `META-PROVENANCE` | **Gold is spec-first, not output-fitted** | every gold / expected-outcome case carries a provenance note deriving it from the **spec/intent**; no gold value was edited in the same change that observed the output it matches; gold changes trace to a human-reviewed gold-change request (`RULE_METRIC_FALSIFIABLE`; Metric Integrity #5; cross-refs Verifier-Independence) |

---

### Live, gated checks (skipped without `ANTHROPIC_API_KEY`)
`DRAFT2` (real-lane error path) and the `make demo-live` smoke are the only live checks; everything
else is offline and deterministic. A live check is **SKIPPED, never failed**, when the key is absent.

---

## §16. Intelligent Query Refinement (`QREF*`, `DRAFT-COT*`) — Stage 10 (ADD-only)

> New LLM stage **before** retrieval (raw question → optimized search query) + the original question
> reaching the draft prompt + a `<thinking>` reason-then-strip scaffold. Verified offline/deterministic
> (`tests/test_stage10_query_refinement.py`, 25 tests). The `<thinking>` self-checks are **defense-in-depth
> UX, not enforcement** — the `RULE_*` chokepoints stay code-enforced (CLAUDE.md §5). Cross-references the
> Stage 3 modules (`context_stack.py`, `llm.py`, `draft.py`) without retro-editing the ✅ Stage 3/4 DoD.

| ID | Gate | How it is checked |
|---|---|---|
| `QREF1` | `<thinking>` strip is deterministic & total | `strip_thinking_block` removes well-formed, dangling-open, case-insensitive, and multiple blocks; empty remainder → caller fallback (`TestStripThinkingBlock`) |
| `QREF2` | Refinement is identity offline + safe-fallback | `MockLLM.refine_query(q) == q` (offline determinism preserved); the `app/query_optimizer.refine_query` wrapper degrades to the original question on empty / thinking-only / non-alphanumeric / exception / runaway-length output (`TestRefineQueryWrapper`) |
| `QREF3` | Pipeline injects + audits the stage | `run_pipeline` emits one `refine_query` `tool_call` audit event per item with `original` + `optimized`; offline `optimized == original`; a rewriting provider's optimized query is the one audited (`TestPipelineRefinement`) |
| `DRAFT-COT1` | Original question reaches the draft prompt | `assemble_context(...).question == item.question`; `item.question in ClaudeLLM()._build_prompt(stack)` (the **defect regression**); the prompt carries the `<thinking>` directive; pre-Stage-10 `ContextStack(...)` still validates (default `""`) (`TestContextStackQuestion`) |
| `DRAFT-COT2` | Draft strips `<thinking>` before gate/export | with only the Anthropic client faked (real `_build_prompt`/`draft`/strip path), a `<thinking>…</thinking> answer [chunk_id]` response yields `DraftAnswer.text` with no `<thinking>` and a parsed citation; a thinking-only response degrades to `UNGROUNDED_PLACEHOLDER`; `MockLLM` never emits `<thinking>`; the directive constants carry the three required checks (`TestDraftThinkingStrip`, `TestPromptScaffoldConstants`) |
