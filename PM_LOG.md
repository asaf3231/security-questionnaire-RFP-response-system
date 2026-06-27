# PM_LOG.md — PM→PM Session Handoff Log

Project: **Reindeer Security-Questionnaire / RFP Response Agent** (codename TBD at spine genesis)
Maintained by: Asaf (PM). **Only the PM writes this file.** Append-only; never edited in place.

> Session-level PM→PM continuity (begin/end ritual, per `PM_Methodology_Prompt.md`). Distinct from
> `NOTES.md` (decisions + handback pointers) and `FACTS.md` (the only home for numbers). On resume,
> read `STATE.md` first; drop here only if the checkpoint is insufficient.

---

## 2026-06-27 11:21 — [SPINE] SESSION START
Picking up: **fresh project, Stage 0 (genesis)**. No prior `STATE.md` / `PLAN.md` to reconcile —
this is the first PM session. `git status` clean except untracked `Assignment.md`; HEAD `eadf778`
("Frame work setup"); branch `main`; no test suite exists yet (baseline = 0).
State as read (to re-verify): repo contains `PM_Methodology_Prompt.md`, `ORCHESTRATION.md`,
`Assignment.md`, and a read-only `Reference/` spine (the Alta voice-agent project — used as a
**quality bar only**, not for content/domain). No spine files (`CLAUDE.md`/`PLAN.md`/`QA_checklist.md`/
`FACTS.md`/`STATE.md`/`NOTES.md`) exist yet.
Plan for this session: read methodology + orchestration + assignment (done); surface the blocking
ambiguities to Asaf (Zero-Guessing, Phase 3); then author the full repo-root spine (CLAUDE/PLAN/
QA/FACTS/STATE/NOTES) to the Reference quality bar; stop at the spine boundary and walk Asaf through
it before any implementation or subagent execution.

## 2026-06-27 11:21 — [SPINE] SESSION END / HANDOFF
Did: Resolved the four Zero-Guessing forks with Asaf (service repo + offline-core/gated-live;
`rank_bm25` lexical retrieval; brief+appendix as first-class stages; hybrid confidence). Asaf then
added five AI-Ops architectural principles (Agent Context Stack/backpack; recall-first + `rank_bm25`
external lib + paragraph chunks; code-not-prompt HITM harness with the three routing triggers;
property-validator confidence + LLM-rationale; grep-enforceable `RULE_*` registry) — all folded into
the spine. **Authored the full repo-root spine:** `CLAUDE.md` (env, pinned deps, import-safety, the
11-rule `RULE_*` registry §5 with chokepoints + audit reason-codes + QA IDs, the 4-layer Context
Stack, the 7-failure anti-leakage rule §5.2, §9 constants + byte-exact literals), `QA_checklist.md`
(stable IDs across `ENV/SEC/KB/DATA/RET/CTX/SCHEMA/DRAFT/GROUND/CONF/ROUTE/STATUS/AUDIT/EXPORT/BOUND/
PIPE/DEMO/EVAL/LEAK/RULE/PKG/DOC`), `PLAN.md` (stages 0–9, every DoD citing QA IDs + reviewer-gate
triggers), `FACTS.md` (ledger header + pending rows), `NOTES.md` (genesis decisions D-1..D-7 + OQ-1/
OQ-2), `STATE.md` (Stage 0 checkpoint). **PM cross-checks run + green:** every PLAN QA ID resolves;
all 11 `RULE_*` have exactly one registry row + ≥1 QA mention; no stray threshold literals outside
`CLAUDE.md` §9 / `FACTS.md`; `Reference/` untouched; nothing committed (awaiting Asaf's word).
Status now: 🟡 Stage 0 spine authored — **awaiting Asaf green-light**. No code yet; suite baseline 0.
Next PM should: get Asaf's green-light + OQ-1 (`DRAFT_MODEL` pin) + OQ-2 (export format) + codename
confirm; then brief **Stage 1** (Environment, secrets, config & synthetic inputs) and spawn the first
cold `general-purpose` executer per `ORCHESTRATION.md`. Do not advance past Stage 1's boundary.
Watch out for / open: spine is uncommitted (commit only on Asaf's instruction; suggest a
`stage-0-spine` baseline tag once approved); `DRAFT_MODEL` still unpinned — `claude-api` skill to be
consulted at Stage 1; `.DS_Store` noise + untracked `Assignment.md` present.

## 2026-06-27 11:40 — [BACKEND] SESSION START
Picking up: **Stage 0 ✅ APPROVED by Asaf** (architecture + spine locked); authorized to commit the
baseline and execute **Stage 1** (Environment, secrets, config & synthetic inputs) under the
ORCHESTRATION.md autonomous loop, then STOP at the Stage 1 boundary and hand back.
State as read (to re-verify): OQ-1 resolved → `DRAFT_MODEL=claude-sonnet-4-6` (already §9 default);
OQ-2 resolved → export Markdown + CSV; codename "Comet" confirmed. Asaf emphasis: **strictly enforce
`KB1`/`DATA1`** (data integrity before retrieval) — folded into Stage 1 via the load+validate half of
`app/kb.py` (plan refinement, see PLAN Stage 1).
Plan for this session: (1) commit the Stage 0 spine baseline on `main` + tag `stage-0-spine`;
(2) write `briefs/stage-1.md`; (3) spawn a cold `general-purpose` executer (Sonnet); (4) PM re-runs
`ENV*`/`SEC*`/`KB*`/`DATA1` + `make test` independently; (5) `/code-review` gate (graded contracts);
(6) record FACTS, mark Stage 1, commit, and hand back to Asaf at the boundary. Do not advance to Stage 2.

## 2026-06-27 12:05 — [BACKEND] SESSION END / HANDOFF
Did: **Stage 0 committed** (`abb793a`, tag `stage-0-spine`). **Stage 1 executed via the autonomous
loop and PM-verified ✅.** Cold `general-purpose` executer built the env/config/schema/kb + synthetic
data + tests. PM independent QA: `make test` 39 green (re-run myself), ENV4 import-safe, SEC1 clean
(my own independent scan — zero real-key shapes), KB1/DATA1 **strict `ValueError`** confirmed (Asaf
emphasis). **`/code-review` gate:** 1 Important finding (10 premature stub modules vs CLAUDE §8) →
fixed via a **warm-agent SendMessage** (cheaper than a cold respawn): stubs removed, app/ now only
config/schema/kb; ENV4 made progressive in the spine + test. 2 minor kb.py findings deferred to Stage
2. **Verifier-independence event:** the executer also tightened the `SEC1` regex (its own handback
prose had tripped the loose heuristic); PM re-ran at the pre-edit revision + scanned independently →
**strengthening, no secret masked → accepted** (NOTES D-S1). Verified numbers in FACTS (suite/ENV4/
KB-size/deps). Committed as `stage-1-env`. Handback NOT pasted here — pointer in NOTES.
Status now: ✅ Stage 1 complete, committed. Suite 39 green. **HALTED at the Stage 1 boundary per Asaf.**
Next PM should: get Asaf's go-ahead, then brief **Stage 2** (KB chunks + `rank_bm25` retrieval + tag
filter + Recall@K), folding in the two deferred kb.py follow-ups. Stage 2 touches a graded contract
(retrieval signature + BM25 params) → reviewer gate fires.
Watch out for / open: SEC1 test edit accepted as a strengthening (flag to Asaf for visibility — revert
if undesired); system python is 3.10 (too old) — venv uses 3.12.4, so `make test` needs the venv
active; Recall@K fixtures (`fixtures/eval/`) get seeded at Stage 2 for `RET2`.

## 2026-06-27 13:33 — [BACKEND] SESSION START
Picking up: **Stage 1 ✅ verified & locked by Asaf**; authorized to execute **Stage 2** (KB chunks +
deterministic `rank_bm25` retrieval) under the autonomous loop, then HALT at the Stage 2 boundary for
Asaf's manual review.
State as read (to re-verify): suite 39 green (Stage 1, `stage-1-env`); KB 20/19; §9 retrieval constants
present. Asaf's explicit Stage 2 requirements: (1) clear the two deferred kb.py findings first
(dead condition + chunk_id uniqueness); (2) `retrieve(question)` via pinned `rank_bm25`, atomic unit =
full paragraph/approved-answer chunk; (3) strict topic+sensitivity filtering, only `approved==True`
accessible; (4) seed `fixtures/eval/` + compute Recall@K via `rubric.py`, **metrics written to
FACTS.md** (PM records after verifying); (5) full determinism (identical ranked lists). Then
`/code-review` on the graded retrieval contracts.
Plan for this session: write `briefs/stage-2.md`; spawn cold `general-purpose` executer (Sonnet);
PM re-runs `RET1`–`RET3` + determinism + computed-Recall@K independently; `/code-review` gate; record
Recall@K in FACTS; mark Stage 2; commit `stage-2-retrieval`; HALT + handback. Do not advance to Stage 3.

## 2026-06-27 13:55 — [BACKEND] SESSION END / HANDOFF
Did: **Stage 2 executed via the autonomous loop and PM-verified ✅.** Cold executer built
`app/retrieval.py` (`rank_bm25` BM25Okapi, exact graded `retrieve()` signature, deterministic
tokenizer + `(-score, chunk_id)` sort, approved-only + topic + sensitivity filters), recreated
`app/eval/` (`rubric.compute_recall_at_k`, `fixtures`), seeded `fixtures/eval/` (12 labeled gold),
and cleared both deferred `kb.py` findings (dead condition + chunk_id-uniqueness `ValueError`). PM
independent QA: `make test` **71 green** (re-run), **Recall@5 = 1.0000** re-computed (perturb→0.0
proves `RULE_NO_FABRICATED_METRIC`), determinism re-checked (run1==run2; no non-approved returned).
**Verifier-independence:** `tests/test_stage1.py` UNTOUCHED (executer added a new ENV4-progressive test
in `test_stage2.py` instead of editing the existing one) — clean. **`/code-review` gate: APPROVE**, no
correctness findings; 1 minor efficiency note (BM25 rebuilt per `retrieve()` call) → deferred to Stage
6. Verified numbers in FACTS (suite/Recall@K/import-safety scope). Committed `stage-2-retrieval`.
Status now: ✅ Stage 2 complete, committed. Suite 71 green. **HALTED at the Stage 2 boundary per Asaf.**
Next PM should: get Asaf's go-ahead, then brief **Stage 3** (Context Stack + draft + grounding;
`CTX1`–`CTX4`/`SCHEMA1`/`DRAFT1`–`DRAFT2`/`GROUND1`) — graded contracts (LLMProvider interface, schema,
byte-exact `UNGROUNDED_PLACEHOLDER`, `RULE_GROUNDED_ONLY`) → reviewer gate fires. DRAFT2 is live-gated.
Watch out for / open: Stage 6 efficiency follow-up (build BM25 index once); Recall=1.0 is honest but
reflects a small/easy synthetic corpus — good Q&A talking point, not a defect; `make test` needs venv.

## 2026-06-27 14:10 — [BACKEND] SESSION START
Picking up: **Stage 2 ✅ verified & locked by Asaf**; authorized to execute **Stage 3** (Context Stack
+ draft generation + grounding) under the autonomous loop, then HALT at the Stage 3 boundary for Asaf.
State as read (to re-verify): suite 71 green (`stage-2-retrieval`); Recall@5=1.0; retrieval
deterministic. Asaf's Stage 3 reqs: (1) `context_stack.py` strict 4-layer Pydantic contract,
Retrieval layer = ONLY the exact Stage-2 chunks; (2) `LLMProvider` ABC + `MockLLM` (offline det.) +
`ClaudeLLM` (lazy, network-gated); (3) `draft_answer(context_stack)` → text + structured `citations[]`;
(4) strict literal grounding gate (`RULE_GROUNDED_ONLY`) → byte-exact `UNGROUNDED_PLACEHOLDER` +
`GROUNDING_FAIL`; (5) live/network errors degrade to routed-for-review placeholder, no unhandled
exceptions.
Plan for this session: write `briefs/stage-3.md` (incl. the design decisions: chunk_id markers in the
retrieval layer so citations carry ids; **add `GROUNDING_COVERAGE_MIN` + `GROUNDING_FAIL` to §9/config**
— flagged); spawn cold `general-purpose` executer (Sonnet); PM re-runs `CTX*`/`SCHEMA1`/`DRAFT1`/
`GROUND1` + offline degradation + determinism independently; `/code-review` gate; record FACTS; mark
Stage 3; commit `stage-3-draft`; HALT + handback (surfacing the new constants). Do not advance to Stage 4.

## 2026-06-27 14:35 — [BACKEND] SESSION END / HANDOFF
Did: **Stage 3 executed via the autonomous loop and PM-verified ✅.** Cold executer built
`app/context_stack.py` (4-layer backpack; Retrieval = only passed chunks, `[chunk_id] text`),
`app/llm.py` (`LLMProvider` ABC + deterministic `MockLLM` + lazy/gated `ClaudeLLM` that degrades to
the placeholder), `app/draft.py` (`draft_answer` + `grounding_check` 3-condition gate), and added the
two flagged constants to config. PM independent QA: `make test` **116 pass / 1 skip** (re-run);
grounding gate verified across ALL three ungrounded conditions incl. condition-3 in isolation
(valid-cite + unrelated text → `GROUNDING_FAIL`, byte-exact placeholder); MockLLM determinism +
offline degradation (raising provider → placeholder, no exception) + ENV4 (9 modules, `_claude_client`
None) all re-verified. **Verifier-independence:** `test_stage1.py`/`test_stage2.py` UNTOUCHED;
`config.py` diff = additions-only (no existing value changed). **`/code-review`: APPROVE**, no
correctness findings; documented the lexical-vs-semantic grounding limitation. Synced the two new
constants into `CLAUDE.md` §9 (config↔§9 kept consistent). Committed `stage-3-draft`.
Status now: ✅ Stage 3 complete, committed. Suite 116/1-skip. **HALTED at the Stage 3 boundary per Asaf.**
Next PM should: get Asaf's go-ahead, then brief **Stage 4** (confidence + routing + state machine;
`CONF1`–`CONF3`/`ROUTE1`–`ROUTE3`/`STATUS1`–`STATUS2`) — hybrid confidence (deterministic gate + LLM
rationale), the 3 review triggers, `RULE_NO_SELF_APPROVE` state-machine guard; materialize the §5.1
reason-codes Stage 4 needs. Graded contracts → reviewer gate fires.
Watch out for / open: the two NEW §9 constants are flagged for Asaf's review (revert/retune if
desired); grounding is lexical not semantic (known limitation); Stage 6 BM25-rebuild efficiency
follow-up still open; `make test` needs venv.

## 2026-06-27 14:55 — [BACKEND] SESSION START
Picking up: **Stage 3 ✅ verified & locked by Asaf** (grounding trade-off approved as a Q&A asset);
authorized to execute **Stage 4** (confidence + routing + state machine) under the autonomous loop,
then HALT at the Stage 4 boundary for Asaf.
State as read (to re-verify): suite 116/1-skip (`stage-3-draft`); §9 thresholds + queues + ITEM_STATES
present. Asaf's Stage 4 reqs: (1) hybrid confidence — number from property validators (retrieval
quality/coverage/grounding), LLM rationale ONLY, threshold banding from config; (2) routing engine —
the 3 `RULE_HITM_REVIEW_TRIGGER` triggers (high-risk tag / ambiguity / score < review threshold) →
reviewer queues; (3) state machine — legal `ITEM_STATES` transitions, rigid `RULE_NO_SELF_APPROVE`
boundary (agent can never auto-transition to approved/final), explicit errors on invalid transitions.
Plan for this session: write `briefs/stage-4.md` (incl. D-S4 design + the §9 additions:
`DEFAULT_REVIEWER_QUEUE` + 4 reason-codes); spawn cold `general-purpose` executer (Sonnet); PM re-runs
`CONF*`/`ROUTE*`/`STATUS*` + score-is-deterministic + self-approve-blocked independently; `/code-review`
gate; record FACTS; mark Stage 4; commit `stage-4-routing`; HALT + handback. Do not advance to Stage 5.

## 2026-06-27 15:25 — [BACKEND] SESSION END / HANDOFF
Did: **Stage 4 executed via the autonomous loop and PM-verified ✅.** (Note: the first executer spawn
was user-interrupted but had already written the files; the re-spawned executer found them present,
verified, and handed back — PM re-verified everything from scratch regardless of provenance.) Modules:
`app/confidence.py` (hybrid: deterministic 3-validator score + template rationale; LLM never sets the
number), `app/routing.py` (3 triggers, precedence high-risk→ambiguity→low-conf, queue from policy map
+ `DEFAULT_REVIEWER_QUEUE` fallback), `app/state.py` (LEGAL_TRANSITIONS + HUMAN_ONLY_TARGETS +
`transition()` raising InvalidTransition / SelfApproveBlocked). PM independent QA: `make test`
**179 pass / 1 skip** (re-run); CONF1/CONF2 (score model-independent + invariant to rationale),
CONF3 banding, ROUTE1–3, STATUS1/STATUS2 (agent self-approve blocked, human allowed) all re-verified;
**real demo-data routing characterized** (FACTS "demo routing"). **Verifier-independence:**
test_stage1/2/3 UNTOUCHED; config.py additions-only. **`/code-review`: APPROVE** — 1 minor (confidence
rationale recomputes coverage/dominance → deferred Stage 7); Stage-6 note (case_confident-i3 routes via
security tag). Synced the 5 new constants into §9. Committed `stage-4-routing`.
Status now: ✅ Stage 4 complete, committed. Suite 179/1-skip. **HALTED at the Stage 4 boundary per Asaf.**
Next PM should: get Asaf's go-ahead, then brief **Stage 5** (audit log + export + hard boundary;
`AUDIT1`–`AUDIT3`/`EXPORT1`–`EXPORT3`/`BOUND1`–`BOUND2`) — append-only JSONL (`RULE_AUDIT_COMPLETE`),
Markdown+CSV export of APPROVED only (`RULE_NO_EXTERNAL_SEND` + `RULE_SENSITIVITY_GATE` + byte-exact
`REVIEW_BANNER`); materialize `SENSITIVITY_HOLD`/`EXTERNAL_SEND_BLOCKED`. Reviewer gate fires.
Watch out for / open: 5 new §9 constants flagged for Asaf; case_confident-i3 demo nuance (Stage 6);
confidence-rationale dup (Stage 7 minor); ambiguity uses absolute BM25 gap (works here); `make test` needs venv.
