# CLAUDE.md — Reindeer RFP / Security-Questionnaire Agent ("Comet")

An internal AI agent that takes a security questionnaire / RFP, drafts **grounded** answers from a KB
of prior **approved** responses, scores confidence, **routes** risky items to a human reviewer, tracks
state, and exports an **auditable** response doc. Python service repo + CLI + offline deterministic
eval suite. Two written deliverables (Brief, Technical Appendix). Maintained by Asaf.

> Read this file first every session — it holds the **permanent rules**. Live status: `STATE.md`
> (resume here) → `PLAN.md` (stage tracker) → `QA_checklist.md` (TDD blueprint) → `FACTS.md` (the only
> home for verified numbers) → `NOTES.md` (decisions). Don't duplicate across them.

---

## How to work (read before touching code)

Four behavioral defaults, in priority order. They govern *how* you work; §4 governs *what's allowed*.

1. **Think before coding.** Don't assume; don't hide confusion. If a stage spec, a `RULE_*`, or a
   threshold is ambiguous, state the interpretations and ask — never pick one silently. A wrong guess
   on a graded contract is a halt, so surface it as `DECISION-NEEDED` *before* writing code.

2. **Simplicity first.** Ship the minimum code that satisfies this stage's DoD and its QA IDs —
   nothing speculative. No abstraction with one caller, no config knob nobody asked for, no handling
   for inputs the schema forbids. Test: would a senior engineer call this overcomplicated? If yes,
   cut it. The one thing you never trim is a `RULE_*` chokepoint or an audit event.

3. **Surgical changes.** Touch only what this stage requires. Don't refactor adjacent modules, don't
   restyle code you aren't changing, match the surrounding idiom. Remove only the imports/variables
   *your* change orphaned. Never edit a graded artifact (`tests/`, `fixtures/`, eval gold) to make a
   check pass — that's a finding, not a fix (`RULE_GRADED_ARTIFACT_LOCK`).

4. **Goal-driven execution.** Every stage already defines success: its DoD → its QA IDs. Write the
   check first (TDD), make it pass, then **run** it — never inspect-and-assume. Stop at the stage
   boundary and hand back; don't silently continue into the next stage.

**Graded contracts — never change without surfacing to Asaf first:** any value in `app/config.py`,
both byte-exact literals (§5), a tool/function signature, the `LLMProvider` interface, a Pydantic
schema in `app/schema.py`, any `RULE_*` identifier or its chokepoint, a confidence threshold, the
routing table, or the audit-event schema. If `PLAN.md`, `QA_checklist.md`, or `NOTES.md` is missing,
draft it and wait for approval — don't implement.

---

## 0. Spine & deliverables

File-based PM workflow; each file owns one thing.

| File | Owns |
|---|---|
| `STATE.md` | current checkpoint — the single overwritten resume snapshot (read first) |
| `CLAUDE.md` | permanent rules (this file) |
| `PLAN.md` | stage tracker + Definition of Done |
| `QA_checklist.md` | the TDD blueprint — every DoD points to a check here |
| `FACTS.md` | Verified-Facts Ledger — the **only** place a hard number lives |
| `NOTES.md` | decisions, open questions, handback pointers |
| `PM_LOG.md` / `STATE.md` | PM-only: session handoff + checkpoint |
| `PM_Methodology_Prompt.md` / `ORCHESTRATION.md` | how the PM works / the autonomous PM↔executer loop |

**Roles** (methodology → this env): executer = cold `general-purpose` subagent, one per stage; reviewer
gate = `/code-review`; Stage-8 governance gate = `/security-review`; QA = the PM itself (re-runs the
checks, never marks ✅ on the executer's word). Reviewer ≠ executer ≠ PM-as-QA. Under `ORCHESTRATION.md`
the PM may auto-advance clean stages; the human gate fires only on a needed decision/secret, a
graded-contract change, a 2nd consecutive QA failure, or verifier-independence (the executer weakened a
graded check, or a retry diff touched only `tests/`).

**Three deliverables.** (1) the **service repo** — clean-checkout run, import-safe, intake → exported
auditable doc, passes the offline suite, two mandatory demo cases (§6); (2) the **Brief/Deck** (1–2 pp,
for AEs/SEs/Security/Legal; every number references `FACTS.md`); (3) the **Technical Appendix** —
prompt/tool design, schema, guardrails, routing, audit.

---

## 1. Environment

- **Python 3.11+, OS-agnostic.** No hardcoded absolute paths — build paths with `pathlib` from the repo
  root. No network server, no external integration by design (`RULE_NO_EXTERNAL_SEND`); the only
  outbound call anywhere is the Claude API, only in the gated live draft lane.
- **One-command reproduce from a clean checkout:**
  ```bash
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env.example .env        # fill ANTHROPIC_API_KEY locally — NEVER commit .env
  make test                   # offline deterministic suite (no network, no secret)
  make demo                   # full pipeline on the two demo cases (mocked LLM)
  make demo-live              # the ONLY path that touches the Claude API; still no external send
  ```
- **Import-safe (`ENV4`, non-negotiable).** Every `app.*` module imports with zero side effects — no
  network, no Claude client, no `.env`, no `data/*` read, no file written. Clients are lazy singletons
  (`_get_claude()`). Modules are created as their stage lands (no premature stubs).
- **Pinned deps (`ENV2`).** `requirements.txt` pins every non-stdlib import with `==`; a fresh venv
  installs cleanly. Required: `pydantic`, `rank_bm25` (use the lib, don't hand-roll BM25), `anthropic`
  (live lane only), `python-dotenv` (loaded in main/CLI, never at import), `pytest`. A missing
  transitive that breaks the fresh install is a Stage-1 blocker.
- **Secrets** come from `os.environ` (untracked `.env`; `.env.example` holds placeholders only), never
  hardcoded/committed; the Claude key never enters a tracked file, log, audit, export, or prompt
  (`RULE_NO_SECRET`).

---

## 2. Repo layout & data

`app/` modules in dependency order, each one responsibility + the `RULE_*`/QA it owns: `config.py` (the
only home for magic values) · `schema.py` (Pydantic models) · `kb.py` (loader+validate, `KB1`) ·
`retrieval.py` (rank_bm25 + tag filter, `RET1/2`) · `context_stack.py` (the 4-layer backpack,
`CTX1..4`) · `llm.py` (`LLMProvider`: MockLLM + ClaudeLLM) · `draft.py` (`grounding_check`,
`RULE_GROUNDED_ONLY`/`GROUND1`) · `confidence.py` (`CONF1..3`) · `routing.py`
(`RULE_HITM_REVIEW_TRIGGER`/`ROUTE1..3`) · `state.py` (`RULE_NO_SELF_APPROVE`/`STATUS2`) · `audit.py`
(`RULE_AUDIT_COMPLETE`/`AUDIT1..3`) · `export.py` (`RULE_NO_EXTERNAL_SEND` + `RULE_SENSITIVITY_GATE`) ·
`pipeline.py` (`RULE_SAFE_TERMINAL`/`PIPE2`) · `eval/` (held-out harness, computed rubric, fixtures).
Supporting: `data/` (synthetic inputs) · `fixtures/eval/` (held-out gold) · `tests/` · `scripts/`
(`run_demo.py`, `run_live_draft.py`) · `exports/`+`audit/` (generated, gitignored) · `brief/`+`appendix/`
(deliverables) · `requirements.txt`, `.env.example`, `Makefile`, `README.md`, the spine files.

`data/*.synthetic.*` are loaded **by name** and validated on load (`KB1`/`DATA1`); their values are
**never hardcoded** into a tool or prompt (`LEAK3`). Generated `exports/`+`audit/` and any real
customer data are never committed.

---

## 3. Pipeline (happy path) & runtime contract

```text
questionnaire (data/questionnaires/*.synthetic.json)                    [INTAKE]
 → per item: retrieve → assemble_context → draft_answer + grounding_check → DRAFTED
             score_confidence + LLM rationale → SCORED
             route_for_review(tags, ambiguity, confidence)
               ├─ trigger → ROUTED_FOR_REVIEW → (human) REVIEW_APPROVED | REVIEW_REJECTED
               └─ none    → confident draft, still awaits human APPROVED  (RULE_NO_SELF_APPROVE)
             write_audit(every transition + tool call)
 → export_response  (APPROVED items only, local disk only)  → EXPORTED   (BOUND1)
```

1. Input is a **questionnaire record** (a list of items), not a chat; validate `data/*` on load — a
   malformed input is a clean startup error, not a crash. Each item carries a state (`ITEM_STATES`)
   and advances only through the state machine.
2. Every transition, tool call, retrieval result, confidence number, and routing decision is recorded
   in the append-only audit log (`RULE_AUDIT_COMPLETE`) — the spine of trust; never holds a secret or
   unredacted real PII.
3. **Fail safe, never crash** (`RULE_SAFE_TERMINAL`). Any failure ends in a routed terminal with
   `UNGROUNDED_PLACEHOLDER` + an audit event — never an uncaught exception (one in `pipeline.py` is a
   defect), never a fabricated answer.
4. **The backpack is the only context the model sees** (`CTX1`) — nothing beyond the retrieved chunks
   + the 4 declared layers reaches it.

**Input shapes** (validated on load; owned by `schema.py`/`kb.py`): `approved_answers` = {chunk_id,
question, answer, source, sensitivity, topic_tags[], approved} — required chunk_id/answer/sensitivity,
only `approved==True` is retrievable (`KB1`); `questionnaires` = {questionnaire_id, items[{item_id,
question, topic_tags[]}]} — required questionnaire_id/item_id/question (`DATA1`); `policy_tags` defines
`SENSITIVITY_TAGS`, `HIGH_RISK_TAGS`, and the tag→reviewer-queue map.

---

## 4. Governance — the `RULE_*` registry

**The agent is restrained by code and deterministic rules, not by prompts** (Asaf, Harness
Engineering). Every `RULE_*` has one **code chokepoint** that emits the string, an **audit reason-code**
when it fires, and a **QA ID** that scans for it; one with neither chokepoint nor QA check is a spine
defect.

### 4.1 Runtime rules

| `RULE_*` | Contract | Chokepoint | Audit code | QA |
|---|---|---|---|---|
| `RULE_GROUNDED_ONLY` | Asserted answer cites ≥`GROUNDING_MIN_CITATIONS` chunk, is covered by them (≥`GROUNDING_COVERAGE_MIN`) AND the cited evidence addresses the question (≥`GROUNDING_QUESTION_COVERAGE_MIN`); else `UNGROUNDED_PLACEHOLDER` + route. *(hallucination)* | `draft.py` `grounding_check` | `GROUNDING_FAIL` | `GROUND1`, `LEAK-G` |
| `RULE_NO_SELF_APPROVE` | Agent never transitions to `APPROVED`/`EXPORTED`; only a human does. | `state.py` guard | `SELF_APPROVE_BLOCKED` | `STATUS2`, `BOUND2` |
| `RULE_HITM_REVIEW_TRIGGER` | Route to a human, by precedence: (1) high-risk tag, (2) ambiguous retrieval (top1−top2 < `AMBIGUITY_SCORE_MARGIN`), (3) confidence < `CONFIDENCE_REVIEW_THRESHOLD`, (4) internal/restricted → `SENSITIVITY_REVIEW_QUEUE`. | `routing.py` | `ROUTED_HIGH_RISK`/`_AMBIGUOUS`/`_LOW_CONFIDENCE`/`_SENSITIVE` | `ROUTE1..3` |
| `RULE_NO_EXTERNAL_SEND` | No path sends a response outside the company; `export` is local-disk-only, `APPROVED` items only. *(external send — hard boundary)* | `export.py` | `EXTERNAL_SEND_BLOCKED` | `BOUND1` |
| `RULE_SENSITIVITY_GATE` | A `restricted`/`internal` chunk never exports without human `REVIEW_APPROVED`. *(sensitivity-tag)* | `export.py` + `routing.py` | `SENSITIVITY_HOLD` | `LEAK-S`, `EXPORT2` |
| `RULE_NO_SECRET` | Keys/tokens only in untracked `.env`; never in a tracked file/log/audit/export. *(secret)* | `.gitignore` + grep | (pre-commit) | `SEC1`, `LEAK1` |
| `RULE_NO_REAL_PII` | Only synthetic data tracked; no real customer data. *(PII)* | `.gitignore` + grep | (pre-commit) | `LEAK2`, `LEAK3` |
| `RULE_NO_EVAL_CONTAMINATION` | The questionnaire under test is held out of the KB it's answered from. *(train/test)* | `eval/harness.py` split | (eval-time) | `EVAL2`, `LEAK4` |
| `RULE_NO_FABRICATED_METRIC` | Every metric is computed from a labeled input; never hardcode a score/confidence/approval. *(fabricated outcome)* | `eval/rubric.py` + `tests/` | (eval-time) | `EVAL1`, `LEAK5` |
| `RULE_AUDIT_COMPLETE` | Every transition + tool call emits exactly one append-only audit event; no silent gap. | `audit.py` | (covers all) | `AUDIT1..3` |
| `RULE_SAFE_TERMINAL` | Any failure ends in a clean disposition + audit event; no uncaught exception, no silent partial export. | `pipeline.py` | `ERROR_TERMINAL` | `PIPE2` |

The italic tags mark the seven leakage classes (hallucination, secret, PII, train/test, fabricated
outcome, sensitivity-tag, external send).

### 4.2 Governance-tier rules (guard the verification *process*, not the runtime)

No app chokepoint — enforced by the `make test`/`make eval` pre-flight
(`scripts/check_graded_artifacts.sh`) + the `META-*` checks (`PM_Methodology_Prompt.md` → *Metric
Integrity & Anti-Gaming*).

| `RULE_*` | Contract | QA |
|---|---|---|
| `RULE_GRADED_ARTIFACT_LOCK` | `tests/`, `fixtures/`, eval gold, expected-output snapshots are read-only for modify/delete. **Adding** is fine; **modify/delete** needs two-key human auth (`ALLOW_GRADED_EDIT=1`) naming the spec change + a pre-edit re-run. A failing check is a finding, never "fixed" by editing the check. | `META-LOCK` |
| `RULE_METRIC_FALSIFIABLE` | Every metric runs the **real internal path** (mock only external boundaries — network/clock/model/RNG — with non-constant fakes; no `_simulate_*` of an internal gate) and has a required "red" negative fixture it must catch. Gold is spec-first, never fitted to output. | `META-FALSIFY`, `META-REALPATH`, `META-PROVENANCE` |

The lock binds the agent; `ALLOW_GRADED_EDIT=1` is a **human** key — never delegated to an agent.

---

## 5. Graded contracts & literals

**All magic values live only in `app/config.py`** — thresholds, queues (`REVIEWER_QUEUES`,
`DEFAULT_REVIEWER_QUEUE`, `SENSITIVITY_REVIEW_QUEUE`), tags (`HIGH_RISK_TAGS`, `SENSITIVITY_TAGS`), the
model id (`DRAFT_MODEL`, default `claude-sonnet-4-6`; opus-4-8 swappable), `RANDOM_SEED`, `ITEM_STATES`,
`AGENT_TOOLS`, every `RULE_*` string, and the audit reason-codes. CLAUDE.md **names** them; it never
copies their values. Changing any value (or an `app/schema.py` model, the `LLMProvider` interface, a
`RULE_*` identifier/chokepoint, the routing table, or the audit-event schema) is a graded contract →
surface to Asaf first (a halt).

**The two byte-exact literals — kept visible here because eval asserts them byte-for-byte (`EXPORT3`,
`GROUND1`):**
```python
REVIEW_BANNER          = "⚠️ PENDING HUMAN REVIEW — NOT APPROVED FOR EXTERNAL RELEASE"
UNGROUNDED_PLACEHOLDER = "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"
```

- `LLMProvider` (`draft(context_stack) -> DraftAnswer`) is the only exit to a model; `MockLLM` +
  `ClaudeLLM` implement it (vendor is a swap behind it). Tool name == schema name == dispatch key
  (assert over `AGENT_TOOLS` at import).
- **Confidence is computed, never model-reported** — from retrieval top-score, question coverage, and
  grounding ratio; the LLM writes the rationale string only (`CONF2`).
- Determinism: same input ⇒ same drafts, confidence, routing, every run (seeded MockLLM, deterministic
  `rank_bm25`, zero-temperature drafting in the live lane).

---

## 6. Demo cases & per-stage done

**Two mandatory demo cases (graded).** Case 1 — confident auto-draft (`case_confident.synthetic.json`):
strong KB coverage, no high-risk tag → high confidence, grounded draft, no trigger → still awaits human
`APPROVED` (`DEMO1`). Case 2 — human-review exception (`case_review.synthetic.json`): policy-sensitive /
low-coverage → a `RULE_HITM_REVIEW_TRIGGER` fires → `ROUTED_FOR_REVIEW` to the right queue with
`REVIEW_BANNER`, never auto-included (`DEMO2`).

**Per-stage completion (ticked before every handback).**
- [ ] Stage module(s) run; every QA ID in its DoD **passes** (run, not inspected); import-safety holds
      (`ENV4` from an empty dir; lazy singletons `None`).
- [ ] No secret / real PII in any tracked file (`SEC1`/`LEAK1`/`LEAK2`); no hardcoded `data/*` values
      in code or prompts (`LEAK3`).
- [ ] Every `RULE_*` this stage touches has a live chokepoint + audit reason-code + passing QA ID;
      literals byte-exact; offline suite deterministic and green.
- [ ] Any reported number verified and recorded in `FACTS.md` (nowhere else). Handback →
      `handbacks/stage-<N>.md`, pointer → `NOTES.md`; the **PM** marks ✅ (re-running the checks).

**Handback format** (payload → `handbacks/`, pointer → `NOTES.md`): what changed · DoD checklist (✅/⚠️,
drafted vs test-verified) · QA results (IDs + pass/fail) · decisions · `DECISION-NEEDED` (graded-contract
change / open question / secret = the halt trigger) · deviations & risks · one next action. Don't
advance stages silently; don't mark ✅ on the executer's word.
