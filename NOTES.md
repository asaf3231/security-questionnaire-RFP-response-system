# NOTES.md — Decisions, Open Questions & Handback Pointers

Project: **Reindeer RFP / Security-Questionnaire Response Agent (codename "Comet")**
Maintained by: Asaf (PM)

> Decisions (the *why*) + per-stage handback **pointers** live here. Numbers live in `FACTS.md`; rules
> in `CLAUDE.md`; status in `PLAN.md`; the checkpoint in `STATE.md`. Never paste a handback payload
> here — it stays on disk under `handbacks/stage-<N>.md`; this file gets only the pointer line:
> `Stage <N> ✅ — handbacks/stage-<N>.md · verdict <APPROVE> · commit <sha>`.

---

## Genesis decisions (2026-06-27)

### D-1 — Deliverable shape + API posture *(graded contract)*
**Decision:** a Python **service repo + CLI**. The **deterministic offline pytest suite (mocked LLM,
seeded) is the graded "Restart & Run All" core**; a separate, explicitly **gated live lane**
(`make demo-live`) uses the provided Claude API key for a real-draft demo.
**Reason:** the assignment allows "working, mocked, or pseudo" and provides a key; the offline-core +
gated-live split (mirroring the `Reference/` project) gives reproducible grading *and* a real-model
demo without making the suite non-deterministic or network-dependent.
**Impact:** `MockLLM` is the default `LLMProvider`; `ClaudeLLM` is lazy + gated; `ENV4` import-safety
and `make test` offline are first-class. See [[CLAUDE.md §1]].

### D-2 — KB retrieval = deterministic lexical (`rank_bm25`) *(graded contract)*
**Decision:** deterministic lexical retrieval via the established **`rank_bm25`** library (pinned,
**not** hand-rolled) + a topic/sensitivity tag filter, over **paragraph / approved-answer chunks** as
the atomic unit. Primary metric **Recall@K**.
**Reason:** Asaf (AI-Ops principle B): recall-first — the LLM can't use evidence it doesn't see;
deterministic retrieval keeps the offline suite reproducible and the confidence signal explainable;
paragraph-level chunks avoid context dilution while keeping complete context for generation.
**Impact:** `RETRIEVAL_TOP_K`/`BM25_K1`/`BM25_B`/`RECALL_AT_K_TARGET` in §9; `RET1`–`RET3`.

### D-3 — Hybrid confidence = property validators + LLM rationale *(graded contract)*
**Decision:** the numerical confidence is a **deterministic** function of retrieval quality + grounding
checks ("property validators"); the **LLM writes the human-readable rationale only** and never the
number.
**Reason:** Asaf (principle D): self-reported LLM confidence is poorly calibrated; a deterministic gate
is testable and the rationale makes the audit log *defensible* to Security/Legal/AE stakeholders.
**Impact:** `CONF1`–`CONF3`; the gate drives `RULE_HITM_REVIEW_TRIGGER`.

### D-4 — Non-code deliverables are first-class stages
**Decision:** agents author the Brief/Deck and Technical Appendix as repo artifacts (Stage 9); Asaf
delivers the live 20-minute presentation.
**Reason:** the assignment lists all four deliverables; the two written ones belong in the repo and
must trace every number to `FACTS.md`.
**Impact:** Stage 9; `DOC1`–`DOC2`.

### D-5 — Harness Engineering: grep-enforceable `RULE_*` registry *(graded contract)*
**Decision:** every governance/anti-leakage/safety boundary is a uniquely-named `RULE_*` (string
constant in `app/config.py`) with a code chokepoint, an audit reason-code, and a QA ID — the agent is
restrained **by code, not by prompt text**. HITM is enforced: the agent **may never self-approve**;
routing triggers (high-risk tag / ambiguity / low-confidence) are code, not suggestions.
**Reason:** Asaf (principles C + E): a boundary verifiable by grepping code/logs is auditable; a
prompt-only boundary is not. A `RULE_*` with no chokepoint or no QA check is a spine defect.
**Impact:** `CLAUDE.md` §5 registry; `RULE1`–`RULE2`; the seven anti-leakage `LEAK*`.

### D-6 — Agent Context Stack ("backpack")
**Decision:** every turn assembles a 4-layer context stack — Instruction / Retrieval / Constraint /
State — in `app/context_stack.py`; **nothing outside the retrieved chunks reaches the model**.
**Reason:** Asaf (principle A): structured context bounds dilution + grounding leakage and makes the
prompt a single auditable chokepoint.
**Impact:** `CTX1`–`CTX4`; cross-checks `RULE_GROUNDED_ONLY`.

### D-7 — Codename "Comet" *(proposal — Asaf may override)*
**Decision (proposed):** call the agent **"Comet"** (a reindeer; fits Reindeer + the speed/clarity
connotation). Used in headers only; not load-bearing. **Open for Asaf to override.**

---

## Anti-leakage — what "leakage" means here (summary; full in `CLAUDE.md` §5.2)
Seven concrete, grep/test-enforced failures, each a `RULE_*`: (1) grounding/hallucination
(`RULE_GROUNDED_ONLY`), (2) secret (`RULE_NO_SECRET`), (3) PII/customer-data (`RULE_NO_REAL_PII`),
(4) eval/train-test contamination (`RULE_NO_EVAL_CONTAMINATION`), (5) fabricated metrics
(`RULE_NO_FABRICATED_METRIC`), (6) sensitivity-tag (`RULE_SENSITIVITY_GATE`), (7) external-send
(`RULE_NO_EXTERNAL_SEND`).

---

## Open questions

- **OQ-1** — ~~pin `DRAFT_MODEL`~~ **RESOLVED 2026-06-27 (Asaf): `claude-sonnet-4-6` locked** — optimal
  balance for a lightweight agentic workflow; best for interactive coding. Already the §9 default, so no
  code change. Offline graded path uses `MockLLM` regardless; this id binds only the gated live lane.
- **OQ-2** — ~~export format~~ **RESOLVED 2026-06-27 (Asaf): support BOTH** — a **Markdown** response
  doc (`exports/*.md`, narrative; for Security/Legal) **and** a **CSV grid** (`exports/*.csv`, one row
  per item: question / status / confidence / queue / citations; for Sales/AEs). Both land at Stage 5
  (`EXPORT1`); both obey `RULE_SENSITIVITY_GATE` + `RULE_NO_EXTERNAL_SEND`.

## Codename — CONFIRMED
**"Comet"** confirmed by Asaf 2026-06-27 (D-7 promoted from proposal to locked).

---

## Structural insights (carried forward for later stages)
- **Modules are created per-stage (progressive ENV4).** `app/` holds only the modules whose stage has
  landed (Stage 1: config/schema/kb); no premature stubs (CLAUDE §8). `ENV4` imports the existing set
  and is re-proven as each stage adds its module.
- **KB is one flat chunk list.** `load_kb()` merges `approved_answers.synthetic.json` + every
  `docs/*.synthetic.json` paragraph into a single `list[RetrievedChunk]`; callers filter
  `.approved == True` for retrieval. The atomic retrieval unit is the full chunk (Asaf principle B).
- **`RetrievedChunk.bm25_score` defaults `0.0` and is *set by retrieval* (Stage 2)** — schema is
  populated ahead in one used module (`schema.py`), which is fine (not a stub module).
- **Recall@K ≠ eval contamination.** For `RET2`, the labeled-relevant `chunk_id` legitimately lives in
  the KB — that is exactly what retrieval must find. The contamination guard (`RULE_NO_EVAL_CONTAMINATION`,
  Stage 7) concerns the *answer-generation* eval holding the questionnaire-under-test out of the KB —
  a different thing. Do not "hold out" the relevant chunk from a Recall@K corpus.
- **Confidence/routing signals come from retrieval.** Stage 4's deterministic gate reads the BM25
  top-score + the top1−top2 gap (`AMBIGUITY_SCORE_MARGIN`), so Stage 2's `retrieve()` must return
  per-chunk scores in a stable, comparable form.

## Stage decisions

### FIX-SEC1 — SEC1 was red since stage-5-export; PM QA miss owned + fixed (2026-06-27)
**What:** `tests/test_stage5.py` embedded **literal** key-shaped fixtures (`sk-ant-ABCDEF…`, 24 chars) to
exercise `redact()`. The SEC1 scanner (`sk-ant-[A-Za-z0-9_-]{20,}` over the tracked set, `test_stage1.py`)
correctly flagged them → **SEC1 has been failing since `stage-5-export`** (verified by re-running at the
tag in a worktree: 1 failed). **My Stage-5 handback reported "232 passed / 1 skip" — that was wrong; it
was 231 passed / 1 failed / 1 skip.** Owned + surfaced to Asaf.
**Fix:** runtime-construct the fixtures (`_FAKE_SK_ANT = "sk-ant-" + "A"*24`) so no literal secret-shape
sits in a tracked file. **SEC1 unchanged** (`test_stage1.py` untouched); the redaction **assertions are
unchanged** — only fixture *construction* changed (literal → runtime). Re-verified: SEC1 green, all 10
redaction tests green, full suite **232 pass / 1 skip**, zero `sk-ant-[20+]` literals anywhere.
**Verifier-independence note:** PM edited a graded test to resolve a fixture-hygiene conflict between
two graded checks (SEC1 vs the redaction tests); neither assertion was weakened (confirmed by re-running
both). **Process lesson:** the Stage-5 suite count was taken from a `tail -2` view that did not surface
the failure — going forward, grep the pytest summary for `failed` explicitly, not just the pass line.

### D-S6 — Stage 6 pipeline/retrieval-refactor design (2026-06-27, PM; flagged for Asaf at boundary)
- **Retrieval refactor (Asaf req #2 — build index ONCE):** add a `Retriever` class that builds the
  `BM25Okapi` index over the **full approved corpus once**; `retrieve()` (and the pipeline) score the
  query against it and **filter results after scoring**. This is the standard RAG pattern (stable
  full-corpus IDF) AND the perf fix — **but it changes BM25 scores** vs Stage-2's per-filtered-corpus
  index. **Guardrail:** `RET1`–`RET3` must stay green and Recall@K must stay ≥ `RECALL_AT_K_TARGET`;
  if not, the executer **HALTS as DECISION-NEEDED** (no test-weakening, no fixture-tuning). PM
  re-verifies Recall@K + the demo behaviors and records the (possibly new) number in `FACTS.md`.
- **Pipeline (`RULE_SAFE_TERMINAL`):** each item runs in a try/except; any component failure →
  item routed to a safe terminal (`ROUTED_FOR_REVIEW`) with `UNGROUNDED_PLACEHOLDER` + an
  `ERROR_TERMINAL` audit event — never an uncaught exception, never a fabricated answer.
- **Human-in-the-loop demo:** the pipeline (agent) advances items only to `SCORED` (confident) or
  `ROUTED_FOR_REVIEW` (it cannot self-approve). `run_demo.py` then **simulates the human action**
  (`transition(..., actor="human")` → `APPROVED`) for the confident non-sensitive items and exports
  only those — faithfully demonstrating the HITM boundary (DEMO1 exports; DEMO2 stays routed).
- **NEW §9 reason-code:** `ERROR_TERMINAL` (last §5.1). **case_confident-i3:** kept as-is — the demo
  highlights its high lexical score overridden + routed to `security` (defense-in-depth).

### D-S4 resolution — case_confident-i3 (2026-06-27, Asaf): KEEP AS-IS
Asaf: keep `case_confident-i3` (security tag → ROUTED_HIGH_RISK) exactly as it is — it is a
**defense-in-depth showcase** (routing fires even inside the "confident" set). Stage-6 demo presents
i1/i2 as the confident auto-drafts and i3 as the in-set routing example. **Open question CLOSED.**

### D-S5 — Stage 5 audit/export/boundary design (2026-06-27, PM; flagged for Asaf at boundary)
- **Additive schema fields on `ResponseDocItem`** (needed by the sensitivity gate): `sensitivities:
  list[str] = []` (the sensitivity tags of the item's cited chunks) + `review_approved: bool = False`
  (did the item pass the `REVIEW_APPROVED` human gate). The Stage-6 pipeline populates them.
- **Sensitivity gate (`RULE_SENSITIVITY_GATE`, EXPORT2):** an item whose `sensitivities ∩
  {internal, restricted}` is **held** from export (SENSITIVITY_HOLD) **unless** `review_approved`;
  non-sensitive APPROVED items export normally.
- **Export = APPROVED-only, local disk** (`exports/<qid>.md` + `.csv`). `render_preview()` renders ALL
  items with the byte-exact `REVIEW_BANNER` prepended when any item is not APPROVED (EXPORT3).
- **`RULE_NO_EXTERNAL_SEND` (BOUND1):** there is NO network primitive in the export layer (enforced by
  a static grep test over `app/export.py` for socket/requests/httpx/smtplib/urllib/http.client); export
  writes an affirmative audit event `rule=RULE_NO_EXTERNAL_SEND` (local-only). BOUND2: non-APPROVED
  items never reach the export (cross-checks `RULE_NO_SELF_APPROVE`).
- **NEW §5.1 reason-codes materialized:** `SENSITIVITY_HOLD`, `EXTERNAL_SEND_BLOCKED`. **Why:** the
  sensitivity gate + the boundary need their audit vocabulary. **How:** synced config↔§9; flagged.


### D-S4 — Stage 4 confidence/routing/state design (2026-06-27, PM; flagged for Asaf at boundary)
- **Confidence number = mean of three bounded property validators** — `coverage` (fraction of the
  question's significant tokens present in retrieved chunks), `grounded` (1.0/0.0 from the Stage-3
  gate), `retrieval_dominance` (top1/(top1+top2), a clean [0,1] signal). Equal-weight mean (not a
  "magic weight" — just the average) → **no new weight constants.** The **LLM never sets the number**;
  the offline rationale is a deterministic template (live-lane LLM rationale is a documented extension,
  not built now → no dead code). `confidence_band(score)` bands via existing §9 thresholds.
- **Routing precedence** (first match sets the reason-code): high-risk tag → ambiguity → low-confidence.
  Queue resolved from the `policy_tags` routing_map over the item's tags; fallback = `DEFAULT_REVIEWER_QUEUE`.
- **State machine** — agent may only advance up to `ROUTED_FOR_REVIEW`; `HUMAN_ONLY_TARGETS`
  = {REVIEW_APPROVED, REVIEW_REJECTED, APPROVED, EXPORTED}. Agent→any human-only target is **blocked**
  (`SELF_APPROVE_BLOCKED`, `RULE_NO_SELF_APPROVE`); illegal edges raise `InvalidTransition`.
- **NEW §9 additions (Asaf-flagged):** `DEFAULT_REVIEWER_QUEUE = "engineering"` (genuinely new —
  fallback queue, kept in §9 not hardcoded inline, and not in data to avoid editing Stage-1 tests/
  fixtures = verifier-independence-safe) + materialized §5.1 reason-codes `ROUTED_HIGH_RISK` /
  `ROUTED_AMBIGUOUS` / `ROUTED_LOW_CONFIDENCE` / `SELF_APPROVE_BLOCKED` (implementing the spec, not new
  decisions). **Why:** routing needs a safe fallback queue + the reason-code vocabulary. **How to apply:**
  synced config↔§9; surfaced at the boundary for Asaf (retune `DEFAULT_REVIEWER_QUEUE` if desired).


### D-S3 — Stage 3 grounding + context-stack design (2026-06-27, PM; flagged for Asaf at the boundary)
- **Citations carry chunk_ids via the Retrieval layer.** `assemble_context` formats each Retrieval-layer
  entry as `"[<chunk_id>] <chunk text>"` so `draft_answer` can cite by id while the layer still holds
  **only** the retrieved chunks' content (CTX1 intent preserved — nothing outside the top-K).
- **New §9 constants Stage 3 adds (additions, not changes to existing contracts):**
  `GROUNDING_COVERAGE_MIN` (default **0.5**) — the content-support threshold needed to satisfy Asaf
  req #4 ("claims not backed by the citations"); and `GROUNDING_FAIL` — the §5.1 audit reason-code
  materialized as a named constant. **Why:** the grounding gate Asaf requested intrinsically needs a
  coverage threshold + a reason-code constant; both are surfaced for Asaf's review at the boundary.
  **How to apply:** the gate is ungrounded if citations < `GROUNDING_MIN_CITATIONS`, OR any cited id ∉
  retrieved set, OR content coverage < `GROUNDING_COVERAGE_MIN` → byte-exact `UNGROUNDED_PLACEHOLDER`.


### D-S1 — Stage 1 SEC1 test modification scrutinized & accepted (2026-06-27)
During the reviewer-gate correction, the executer modified the `SEC1` test (tightened the
secret-scan to `sk-ant-[A-Za-z0-9_-]{20,}`) because its **own updated handback prose** (documenting
the SEC1 check) tripped the prior loose heuristic — a false positive on documentation, not a leak.
**Verifier-independence ruling:** the PM re-ran the check at the pre-edit (staged) revision and ran an
**independent** secret scan — zero real-key shapes / zero non-placeholder `ANTHROPIC_API_KEY=` in any
tracked file. The change still catches any real key + the `ANTHROPIC_API_KEY=` assignment case →
**a strengthening, not a weakening; accepted.** Surfaced to Asaf in the Stage 1 handback.
**Why:** the rule guards against an executer *relaxing a check to mask a real failure*; here nothing
was masked and detection improved. **How to apply:** any future graded-check edit gets the same
treatment — re-run at pre-edit + an independent verification before accept; halt to Asaf on any doubt.

### Stage 2 follow-ups (from Stage 1 review) — ✅ DONE in Stage 2
- ~~Remove the dead `and required_field != "approved"` sub-condition~~ ✅ removed.
- ~~Add a `chunk_id`-uniqueness `ValueError` in `load_kb`~~ ✅ added (across answers + docs).

### Stage 6 follow-up (from Stage 2 reviewer gate — efficiency, non-blocking)
- `retrieve()` calls `load_kb()` and rebuilds the `BM25Okapi` index on **every** call. Fine for the
  20-chunk demo, but the Stage-6 pipeline answers many items per questionnaire → build the index /
  load the KB **once** and reuse (or `functools.lru_cache` on `load_kb`, mindful of test isolation).
  Not a correctness issue; no change made at Stage 2.

## Handback pointers (filled per stage; pointer-not-copy)
Stage 0 ✅ — spine genesis (PM-authored) · commit abb793a · tag stage-0-spine
Stage 1 ✅ — handbacks/stage-1.md · verdict APPROVE (1 finding fixed, SEC1 edit accepted) · tag stage-1-env
Stage 2 ✅ — handbacks/stage-2.md · verdict APPROVE (no findings; Recall@5=1.0 computed) · tag stage-2-retrieval
Stage 3 ✅ — handbacks/stage-3.md · verdict APPROVE (no findings; D-S3 constants added+synced to §9) · tag stage-3-draft
Stage 4 ✅ — handbacks/stage-4.md · verdict APPROVE (D-S4 constants added+synced; 1 minor deferred) · tag stage-4-routing
Stage 5 ✅ — handbacks/stage-5.md · verdict APPROVE (no findings; D-S5 schema+reason-codes added+synced) · tag stage-5-export
Stage 6 ✅ — handbacks/stage-6.md · verdict APPROVE (no correctness findings; Recall@K held 1.0; ERROR_TERMINAL synced) · tag stage-6-pipeline

### D-S6 status (2026-06-27) — IMPLEMENTED & PM-verified + OPEN design question for Asaf
Pipeline + Retriever(build-once, full-corpus IDF) + demo scripts landed; PM-verified suite 278/1,
Recall@K held 1.0, RET1–3 untouched+green, safe-terminal (injected failure → no uncaught exception),
DEMO1/DEMO2 behaviors, RULE1/RULE2 audit coverage; `make demo` clean offline (venv). `ERROR_TERMINAL`
synced to §9. **OPEN DESIGN QUESTION (surfaced to Asaf at the Stage 6 boundary):** internal/restricted
sensitivity is an **export gate** (`RULE_SENSITIVITY_GATE`) but **not a routing trigger** — so a
*confident, internal-sensitivity* item (case_confident-i2) is never routed to a reviewer yet cannot be
exported without `REVIEW_APPROVED` → it's "stuck" and the demo summary currently drops it (neither
exported nor in the pending-review list). **Decision needed:** (a) make internal/restricted sensitivity
ALSO a routing trigger (route i2 to a sensitivity reviewer), or (b) keep export-gate-only and have the
demo/workflow surface "confident draft held pending human review-approval." The demo-summary clarity
fix depends on this choice → deferred until Asaf decides.

> _Per-stage "IMPLEMENTED & PM-verified" verification narratives (D-S3/D-S4/D-S5) compacted to
> `NOTES_archive.md` 2026-06-27 — all re-fetchable from `FACTS.md` + `handbacks/stage-*.md` + tags.
> The design decisions (above) and the handback pointers stay live here._

### Open follow-ups (live)
- **Stage 7 (deferred minor):** `confidence.py` rebuilds coverage/dominance in the rationale builder
  (duplicate of `_compute_score`) — refactor `_compute_score` to return components so the rationale
  reuses them (avoids drift; the rationale is an audit-trust artifact).
- **Stage 6 (demo design) — RESOLVED (Asaf 2026-06-27): keep `case_confident-i3` as-is.** Its
  `security` tag → ROUTED_HIGH_RISK→security is a **defense-in-depth showcase** (high lexical score
  overridden by a structural policy gate). Stage-6 demo presents i1/i2 as the confident auto-drafts and
  i3 as the in-set routing example.
- **Documented (not a defect):** ambiguity trigger uses an absolute BM25 gap vs `AMBIGUITY_SCORE_MARGIN`;
  fine for this corpus (real gaps ~6), but a normalized gap would be more robust at scale (Q&A point).
