# CLAUDE.md — Project Standards & Conventions

Project: **Reindeer RFP / Security-Questionnaire Response Agent** — an internal AI agent that ingests a
new security questionnaire or RFP/RFI, drafts grounded responses from a knowledge base of prior
**approved** answers and product/security docs, scores confidence, **routes** low-confidence or
policy-sensitive items to the right human reviewer, tracks status, and produces an **auditable,
exportable** response document.
Agent codename: **"Comet"** (proposal — `NOTES.md` genesis; Asaf may override).
Deliverable: a **Python service repo + CLI** (the running agent + an offline deterministic test/eval
suite + scripts) **and** two written artifacts — a 1–2 page **Brief/Deck** and a **Technical
Appendix** — see §0.2.
Maintained by: Asaf

> Read this file at the start of every Claude Code session before writing or editing any code. It
> defines the **permanent rules**. The current checkpoint is `STATE.md`; execution status belongs in
> `PLAN.md`; the verification blueprint belongs in `QA_checklist.md`; **verified numbers belong in
> `FACTS.md`** (the only place they live); decisions and handback pointers belong in `NOTES.md`; PM→PM
> session handoff belongs in `PM_LOG.md`.

---

## 0. Working methodology

This project uses the lightweight file-based PM workflow:

```text
STATE.md                 = current checkpoint — the single overwritten resume snapshot (read first)
CLAUDE.md                = permanent rules and conventions  (this file)
PLAN.md                  = current stage tracker and Definition of Done
QA_checklist.md          = the Test-Driven-Development blueprint (every DoD points here)
FACTS.md                 = Verified-Facts Ledger — the ONLY place a hard number/metric lives
NOTES.md                 = decisions, open questions, handback pointers
PM_LOG.md                = PM→PM session handoff log (begin/end ritual)
PM_Methodology_Prompt.md = how the PM works (role, budget rules, memory architecture)
ORCHESTRATION.md         = the autonomous PM↔executer loop protocol (optional)
```

**PM session ritual (non-negotiable):** every PM session opens by reading `PM_Methodology_Prompt.md`
+ **`STATE.md`** (the checkpoint), reconciles it against `git` + the live suite, writes a `SESSION
START` entry to `PM_LOG.md` before working, and writes a `SESSION END / HANDOFF` entry **and
overwrites `STATE.md`** before stopping. Only the PM writes `PM_LOG.md` and `STATE.md`.

At the start of every Claude Code session: read **`STATE.md`** first (reconcile vs `git` + the live
test count), dropping to `CLAUDE.md` → `PLAN.md` → `QA_checklist.md` → `FACTS.md` → `NOTES.md` only if
the checkpoint is insufficient; identify the current stage, work **only** on that stage, stop at the
stage boundary and report back. Do not silently continue into the next stage.

**Graded contracts — never change without surfacing the decision to Asaf first:** a named constant in
§9, a tool/function signature, the LLM-provider interface, a Pydantic schema in `app/schema.py`, any
`RULE_*` identifier or its chokepoint (§5), the byte-exact literals (`REVIEW_BANNER`,
`UNGROUNDED_PLACEHOLDER`, §9), a confidence threshold, the routing table, or the audit-event schema.

If `PLAN.md`, `QA_checklist.md`, or `NOTES.md` is missing, do **not** implement. Draft the missing file
and wait for Asaf to approve it.

### 0.1 Autonomous PM ↔ executer mode (`ORCHESTRATION.md`)
When run under `ORCHESTRATION.md`, the PM performs the stage-boundary review and may auto-advance clean
stages by spawning a cold executer per stage. The human gate (Asaf) narrows to four triggers:
(1) a required decision / open-question / secret; (2) a request to change a graded contract (above);
(3) a second consecutive QA failure on a stage; (4) **verifier-independence** — the executer
weakened/deleted/loosened/`xfail`ed an existing graded check/test/fixture, or a retry diff touched
**only** `tests/` and not `app/` (presumed test-weakening). The executer never crosses its stage
boundary, changes a contract, or grades itself by editing the check that grades it — it surfaces those
as `DECISION-NEEDED`, which the PM converts into a halt (the PM re-runs the check at the pre-edit
revision to confirm the code, not the test, changed).

### 0.2 The three deliverables
1. **The service repo** — graded on the code: it must run from a clean checkout, be import-safe, take a
   new questionnaire from intake to an exported, auditable response document, and pass the offline
   deterministic suite. Two demo cases are mandatory (§11): a **confident auto-draft** and a
   **human-review exception**.
2. **The Brief/Deck** (1–2 pages) — workflow, architecture, assumptions, success metrics; written for
   AEs/SEs/Security/Legal, not only engineers. Every number in it references `FACTS.md`.
3. **The Technical Appendix** — prompt/tool design, the data schema, guardrails, state changes,
   reviewer routing, and audit/logging. Asaf delivers the live 20-minute presentation; the repo
   carries the two written artifacts.

---

## 1. Environment

The service must run in a clean environment with no manual fixups.

- **Python:** 3.11 or higher. **OS-agnostic** (Windows / macOS / Linux): no hardcoded absolute paths;
  build every path with `pathlib` relative to the repo root or `os.getcwd()`.
- **Runtime shape:** a small set of `app/` modules + a CLI (`scripts/`). There is **no network server
  and no external integration** — by design (the hard boundary, §5 `RULE_NO_EXTERNAL_SEND`). The only
  outbound network call permitted anywhere is to the **Claude API**, and only inside the explicitly
  gated **live draft lane** (`make demo-live`); the default suite and `make demo` are fully offline.
- **Reproduce a run from a clean checkout — one command path:**

  ```bash
  python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  cp .env.example .env          # then fill ANTHROPIC_API_KEY locally — NEVER commit .env
  make test                     # the offline deterministic suite — the "Restart & Run All" equivalent
  make demo                     # runs the full pipeline on the two demo cases (mocked LLM, no network)
  ```

  A real-model draft is a separate, explicitly gated command (§5): `make demo-live` — the **only**
  path that touches the Claude API; it still never sends anything externally.

- **Import-safe (non-negotiable):** the full eventual module set —
  `app.config`, `app.schema`, `app.kb`, `app.retrieval`, `app.context_stack`, `app.draft`,
  `app.confidence`, `app.routing`, `app.state`, `app.audit`, `app.export`, `app.pipeline`,
  `app.llm` (+ `app.eval.*`) — must `import` with **zero side effects** — no network, no Claude
  client constructed, no `.env` required, no `data/*` read, no file written. All clients are lazy
  singletons (`_get_claude()`). **Modules are created as their implementing stage lands** (no
  premature stub modules — §8); `ENV4` proves import-safety for the modules that **exist at the
  current stage** and the full set is re-proven as later modules land (Stage 1: `app.config`,
  `app.schema`, `app.kb`).

### 1.1 Pinned dependencies (non-negotiable)
`requirements.txt` pins **every** non-stdlib import with `==`; a fresh venv must `pip install -r
requirements.txt` cleanly. At minimum:

```text
pydantic             # ⚠ pin exact ==version at Stage 1 install — schemas for items, drafts, audit events, context stack
rank_bm25            # ⚠ pin exact — the deterministic BM25 retriever (Asaf: use the established lib, do NOT hand-roll BM25)
anthropic            # ⚠ pin exact — Claude API client; used ONLY in the gated live draft lane (app/llm.py)
python-dotenv        # ⚠ pin exact — loads .env at runtime (inside main/CLI, never at import)
pytest               # ⚠ pin exact — the offline deterministic suite
```

- `os`, `sys`, `json`, `re`, `csv`, `math`, `time`, `random`, `pathlib`, `dataclasses`, `datetime`,
  `enum`, `hashlib`, `importlib`, `typing` are **standard library** — do not list them.
- The Claude model id is the named constant `DRAFT_MODEL` (§9), **pinned at Stage 1 install**
  (`OQ-1`); default `claude-sonnet-4-6`, swappable to `claude-opus-4-8` (a graded contract — surface
  the swap to Asaf). Consult the `claude-api` reference skill before pinning/using the model id.
- A missing/unpinned transitive that breaks the fresh-venv install is a **Stage 1 blocker**, not a
  Stage 9 surprise. `ENV2` fails if any imported module is unpinned.

### 1.2 Providers, models & secrets
| Concern | Choice | Where the secret lives |
|---|---|---|
| Draft generation (live lane only) | **Claude API** via the `anthropic` SDK (`app/llm.py`), `DRAFT_MODEL` | `ANTHROPIC_API_KEY` (env) |
| Draft generation (default/offline) | **`MockLLM`** — deterministic, seeded, no network (the graded path) | none |
| Retrieval | **`rank_bm25`** over the synthetic KB — fully offline | none |
| Confidence number | **deterministic** property validators (no model) | none |

**Every secret comes from `os.environ` (loaded from an untracked `.env`), never hardcoded, never
committed.** `.env.example` carries placeholders only. The provided **Claude API key is a secret** —
it must never appear in any tracked file, commit, log, audit record, exported document, or prompt.
Enforced by `SEC1` / `LEAK1` / `RULE_NO_SECRET`.

### 1.3 Execution & review tooling (this environment's constraints)
The roles named in `ORCHESTRATION.md` (`swe-executer`, `swe-reviewer`) are **roles, not registered
agent types in this environment**. They map to concrete mechanisms here:

| Role (methodology) | Mechanism in this environment | Notes |
|---|---|---|
| Executer (writes stage code) | a **`general-purpose` subagent**, spawned cold per stage with a tight brief + only the relevant diff | never the PM; one per stage, coarse granularity (budget rule) |
| Reviewer gate (contract-touching stages) | the native **`/code-review`** CLI utility | independent of the executer; purpose-built for diffs |
| **Stage 8 governance / anti-leakage gate** | the native **`/security-review`** CLI utility | the highest-leverage gate for this secret- + PII-handling system |
| QA verification | **the PM, itself** (re-runs the referenced `QA_checklist.md` checks) | PM never marks ✅ on the executer's word (§0.1, §12) |

Reviewer ≠ executer ≠ PM-as-QA — the three stay distinct.

---

## 2. Source-of-truth files & repo layout

```text
reindeer-rfp-agent/                      # repo root
├── app/
│   ├── config.py            # §9 constants, RULE_* registry strings, lazy client getter, .env load, literals — the ONLY home for magic values
│   ├── schema.py            # Pydantic models: QuestionnaireItem, RetrievedChunk, ContextStack, DraftAnswer, Citation, ConfidenceResult, RoutingDecision, AuditEvent, ResponseDoc
│   ├── kb.py                # KB loader + validation; atomic chunk = one approved answer / one doc paragraph
│   ├── retrieval.py         # deterministic lexical retrieval via rank_bm25 + sensitivity/topic tag filter; Recall@K
│   ├── context_stack.py     # the 4-layer "backpack" assembler (Instruction / Retrieval / Constraint / State)
│   ├── llm.py               # LLM adapter: MockLLM (offline, seeded) + ClaudeLLM (lazy, gated live lane)
│   ├── draft.py             # prompt/tool-call pattern; draft_answer + grounding_check (RULE_GROUNDED_ONLY)
│   ├── confidence.py        # hybrid score: deterministic property validators + LLM rationale (rationale only)
│   ├── routing.py           # RULE_HITM_REVIEW_TRIGGER: high-risk tag / ambiguity / low-confidence → reviewer queue
│   ├── state.py             # item state machine + status updates; RULE_NO_SELF_APPROVE transition guard
│   ├── audit.py             # append-only JSONL audit log; RULE_AUDIT_COMPLETE
│   ├── export.py            # response-doc renderer (Markdown + CSV grid); RULE_NO_EXTERNAL_SEND + RULE_SENSITIVITY_GATE chokepoint
│   ├── pipeline.py          # orchestrates intake→retrieve→assemble→draft→score→route→status→audit→export; RULE_SAFE_TERMINAL
│   └── eval/
│       ├── harness.py       # offline deterministic eval; RULE_NO_EVAL_CONTAMINATION held-out split
│       ├── rubric.py        # computed metrics (Recall@K, grounding rate, routing accuracy, calibration) — never hardcoded
│       └── fixtures.py      # labeled fixtures loader
├── data/                                # bounded SYNTHETIC inputs — single source of truth, never inlined into code
│   ├── kb/
│   │   ├── approved_answers.synthetic.json   # prior APPROVED Q&A (the retrieval corpus)
│   │   └── docs/                              # product/security docs, paragraph-chunked, tagged
│   ├── questionnaires/
│   │   ├── case_confident.synthetic.json      # demo case 1 — confident auto-draft
│   │   └── case_review.synthetic.json         # demo case 2 — human-review exception
│   └── policy_tags.synthetic.json             # sensitivity-tag definitions + reviewer routing map
├── fixtures/eval/                       # labeled eval gold (held-out; synthetic; tracked)
├── tests/                               # offline deterministic suite (dev-only)
├── scripts/
│   ├── run_demo.py                      # `make demo` — mocked end-to-end over the two cases
│   └── run_live_draft.py                # `make demo-live` — gated live Claude draft (still no external send)
├── exports/                             # generated response docs (gitignored; one redacted sample tracked)
├── audit/                               # generated JSONL audit logs (gitignored)
├── brief/REINDEER_BRIEF.md              # deliverable 2
├── appendix/TECHNICAL_APPENDIX.md       # deliverable 3
├── requirements.txt                     # pinned deps
├── .env.example                         # placeholders only (no real key)
├── .gitignore                           # covers .env, exports/, audit/, .venv, real/customer data
├── Makefile                             # one-command run/test/demo
├── README.md                            # run-from-clean-checkout
└── (spine: CLAUDE.md, PLAN.md, QA_checklist.md, FACTS.md, STATE.md, NOTES.md, PM_LOG.md, ORCHESTRATION.md, PM_Methodology_Prompt.md)
```

Source-of-truth rules:
- `data/*.synthetic.*` are the bounded inputs and the single source of truth for the KB, the incoming
  questionnaires, and the policy/routing map. **Their values are never hardcoded into a tool or
  prompt** (anti-leakage §5). Loaded by name, validated on load (`KB1`/`DATA1`).
- Generated artifacts — `exports/`, `audit/` — are machine-local and **excluded** from commits (one
  redacted sample of each may be tracked for the demo). Real customer questionnaires/answers are never
  committed.
- Do not duplicate decisions across files: rules here, status in `PLAN.md`, why in `NOTES.md`, numbers
  in `FACTS.md`.

---

## 3. System objective & runtime contract

Comet runs a **deterministic, human-gated drafting pipeline**: from an intake questionnaire it
retrieves grounded evidence, assembles a structured context stack, drafts each answer, scores
confidence, routes the risky items to the right human, tracks every state change, and renders an
auditable response document — **never sending anything externally.**

### 3.1 Pipeline shape (the happy path)
```text
new questionnaire (data/questionnaires/*.synthetic.json)        [INTAKE]
  → per item:
     retrieve(question) via rank_bm25 + tag filter              [app/retrieval.py — RET1/RET2]   → RETRIEVED
     assemble_context(item, chunks)  4-layer backpack           [app/context_stack.py — CTX1..4]
     draft_answer(context)  + grounding_check                   [app/draft.py — DRAFT1, GROUND1] → DRAFTED
     score_confidence(retrieval, grounding) + LLM rationale     [app/confidence.py — CONF1..3]   → SCORED
     route_for_review(tags, ambiguity, confidence)              [app/routing.py — ROUTE1..3]
         ├─ trigger fires → ROUTED_FOR_REVIEW → (human) REVIEW_APPROVED | REVIEW_REJECTED
         └─ no trigger    → confident draft, still awaits human APPROVED (RULE_NO_SELF_APPROVE)
     write_audit(every transition + tool call)                  [app/audit.py — AUDIT1..3]
  → export_response (only APPROVED items; local disk only)      [app/export.py — EXPORT1, BOUND1] → EXPORTED
```

### 3.2 Runtime I/O
1. Input is a **questionnaire record** (a list of items; each: `item_id`, `question`, optional
   `topic_tags`) — not a free-text chat.
2. Validate `data/*` on load; a malformed input is a clean startup error, not a mid-pipeline crash.
3. Every item carries a **state** (§9 `ITEM_STATES`) and is advanced only through the state machine.
4. Every transition, tool call, retrieval result, confidence number, and routing decision is recorded
   in the **append-only audit log** (`RULE_AUDIT_COMPLETE`).
5. On any failure (no grounded evidence, model error, validation error), the item ends in a **safe
   terminal** — routed for human input with `UNGROUNDED_PLACEHOLDER`, never an uncaught exception,
   never a fabricated answer (`RULE_SAFE_TERMINAL`).

### 3.3 Governing policies → the `RULE_*` registry (§5)
Every policy is a grep-enforceable `RULE_*` with a code chokepoint, an audit reason-code, and a QA ID.
The summary table lives in §5; nothing in this system is governed by prompt text alone.

---

## 4. The synthetic inputs — operational compliance (non-negotiable)

`data/kb/approved_answers.synthetic.json` records (validate on load — `KB1`):
```text
chunk_id, question, answer, source, sensitivity ∈ SENSITIVITY_TAGS, topic_tags[], approved (bool)
required: chunk_id, answer, sensitivity; only approved==True chunks are retrievable
```
`data/questionnaires/*.synthetic.json` records (validate on load — `DATA1`):
```text
questionnaire_id, items[]  where item = { item_id, question, topic_tags[] }
required: questionnaire_id, items[].item_id, items[].question
```
`data/policy_tags.synthetic.json` — defines `SENSITIVITY_TAGS`, `HIGH_RISK_TAGS`, and the
tag→reviewer-queue routing map. **None of these values may be hardcoded into a tool or prompt**
(anti-leakage §5 `RULE_NO_REAL_PII` cross-check `LEAK3`) — they are read at runtime and validated. A
real customer's questionnaire or a real prior answer never enters a tracked file.

---

## 5. Governance, the `RULE_*` registry & the task-specific anti-leakage rule

**Principle (Asaf, Harness Engineering): the agent is restrained by code and deterministic rules, not
by prompts.** Every governance / anti-leakage / safety boundary is a **`RULE_*`** with: a unique
searchable identifier, a single **code chokepoint** where the identifier string is emitted, an **audit
reason-code** raised when it fires, and a **`QA_checklist.md` ID** that scans code/logs for it. A
`RULE_*` with no chokepoint or no QA check is a **spine defect**. The identifiers are defined once as
string constants in `app/config.py` (e.g. `RULE_NO_EXTERNAL_SEND = "RULE_NO_EXTERNAL_SEND"`).

### 5.1 The registry

| `RULE_*` | One-line contract | Chokepoint (module) | Audit reason-code | QA ID |
|---|---|---|---|---|
| `RULE_GROUNDED_ONLY` | Every asserted answer cites ≥ `GROUNDING_MIN_CITATIONS` retrieved chunk; ungrounded ⇒ `UNGROUNDED_PLACEHOLDER` + route, never an invented answer | `app/draft.py` (`grounding_check`) | `GROUNDING_FAIL` | `GROUND1`, `LEAK-G` |
| `RULE_NO_SELF_APPROVE` | The agent never transitions an item to `APPROVED`/`EXPORTED`; only a human action performs that transition | `app/state.py` (transition guard) | `SELF_APPROVE_BLOCKED` | `STATUS2`, `BOUND2` |
| `RULE_HITM_REVIEW_TRIGGER` | Route to a human if **any**: (1) high-risk tag (`HIGH_RISK_TAGS`), (2) ambiguous/contradictory retrieval (top1−top2 gap < `AMBIGUITY_SCORE_MARGIN`, or conflicting chunks), (3) confidence < `CONFIDENCE_REVIEW_THRESHOLD` | `app/routing.py` | `ROUTED_HIGH_RISK` / `ROUTED_AMBIGUOUS` / `ROUTED_LOW_CONFIDENCE` | `ROUTE1`, `ROUTE2`, `ROUTE3` |
| `RULE_NO_EXTERNAL_SEND` | No code path sends a response outside the company; `export` writes to local disk only and only for `APPROVED` items | `app/export.py` | `EXTERNAL_SEND_BLOCKED` | `BOUND1` |
| `RULE_SENSITIVITY_GATE` | A chunk/answer tagged `restricted`/`internal` never enters an export without a human `REVIEW_APPROVED` | `app/export.py` + `app/routing.py` | `SENSITIVITY_HOLD` | `LEAK-S`, `EXPORT2` |
| `RULE_NO_SECRET` | API keys/tokens live only in untracked `.env`; never in any tracked file, log, audit record, or export | `.gitignore` + grep gate | (pre-commit) | `SEC1`, `LEAK1` |
| `RULE_NO_REAL_PII` | Only synthetic KB/questionnaires are tracked; no real customer data, names, or contacts committed | `.gitignore` + grep gate | (pre-commit) | `LEAK2`, `LEAK3` |
| `RULE_NO_EVAL_CONTAMINATION` | The questionnaire under test is **held out** of the KB it is answered from; no gold answer is pre-seeded then "retrieved" | `app/eval/harness.py` (split) | (eval-time) | `EVAL2`, `LEAK4` |
| `RULE_NO_FABRICATED_METRIC` | Every reported metric is **computed** from a labeled input; tests/eval never hardcode a score, a confidence, or an approval | `app/eval/rubric.py` + `tests/` | (eval-time) | `EVAL1`, `LEAK5` |
| `RULE_AUDIT_COMPLETE` | Every state transition and tool call emits exactly one append-only audit event; no silent gap | `app/audit.py` | (covers all) | `AUDIT1`, `AUDIT2`, `AUDIT3` |
| `RULE_SAFE_TERMINAL` | Any failure ends in a clean disposition + audit event; never an uncaught exception, never a silent partial export | `app/pipeline.py` | `ERROR_TERMINAL` | `PIPE2` |

### 5.2 Anti-leakage — what "leakage" means *here* (QA: `LEAK1`–`LEAK5`, `LEAK-G`, `LEAK-S`)
"Leakage"/contamination for this assignment is **seven concrete failures**, each mapped to a `RULE_*`
above and each grep- or test-enforced:

1. **Grounding leakage (hallucination)** — the agent asserting a claim not supported by a retrieved KB
   chunk. The core "safe responses" risk. Blocked by `RULE_GROUNDED_ONLY`: `draft_answer` must cite
   its sources; `grounding_check` rejects an answer whose claims are not covered by the retrieved
   chunks and substitutes `UNGROUNDED_PLACEHOLDER` + routes for human input. (`GROUND1`, `LEAK-G`)
2. **Secret leakage** — `ANTHROPIC_API_KEY` or any token in a tracked file/log/export.
   `RULE_NO_SECRET`. (`SEC1`, `LEAK1`)
3. **PII / customer-data leakage** — real questionnaires, real prior answers, or real prospect data in
   the repo. Only labeled synthetic fixtures are tracked. `RULE_NO_REAL_PII`. (`LEAK2`, `LEAK3`)
4. **Eval/train-test contamination** — the gold answer for a test questionnaire being present in the
   KB used to answer it (so retrieval "finds" the answer it was graded against). The eval **holds the
   questionnaire-under-test out of the corpus**. `RULE_NO_EVAL_CONTAMINATION`. (`EVAL2`, `LEAK4`)
5. **Fabricated outcomes** — tests/eval hardcoding `confidence=high`, a canned draft, or `approved=True`
   and scoring it as a real result. Every metric is computed from a labeled input.
   `RULE_NO_FABRICATED_METRIC`. (`EVAL1`, `LEAK5`)
6. **Sensitivity-tag leakage** — a KB entry tagged `restricted`/`internal` reaching an exported
   document without a human review. `RULE_SENSITIVITY_GATE` is the single chokepoint. (`LEAK-S`,
   `EXPORT2`)
7. **External-send leakage (the hard boundary)** — *any* code path that emails, uploads, posts, or
   otherwise sends a response outside the company. There is **no such path**: `export` writes local
   disk only, only for human-`APPROVED` items, and emits `RULE_NO_EXTERNAL_SEND` to the audit log.
   (`BOUND1`)

---

## 6. Resiliency boundaries (QA: `PIPE2`, `DRAFT2`, `GROUND1`)
- Every component failure (model error in the live lane, malformed KB entry, empty retrieval, schema
  validation error) becomes a **structured result**, surfaced and recovered — it never crashes the
  pipeline. `RULE_SAFE_TERMINAL`.
- An **uncaught Python exception anywhere in `app/pipeline.py` is a defect.** Component failures are
  data, not crashes; the item is routed for human input, never silently dropped or fabricated.
- The live lane (`app/llm.py` `ClaudeLLM`) wraps the API call: on timeout/error it degrades to a
  routed-for-review item, never a partial or invented answer.

---

## 7. Logging, audit & literals
- **The two byte-exact, contractual strings** are `REVIEW_BANNER` and `UNGROUNDED_PLACEHOLDER` (§9).
  They are module constants so they cannot drift; eval asserts them byte-for-byte (`EXPORT3`,
  `GROUND1`).
- **The audit log is the product's spine of trust.** A single append-only JSONL writer
  (`app/audit.py`) records one event per state transition and per tool call, each with: `timestamp`,
  `questionnaire_id`, `item_id`, `event`, `from_state`/`to_state`, `rule` (the `RULE_*` reason-code if
  one fired), and a `detail` object (computed numbers, retrieved `chunk_id`s, queue). **An audit
  record never contains a secret, a raw API key, or unredacted real PII** (`RULE_NO_SECRET`,
  `RULE_NO_REAL_PII`). The audit log is what makes the export **defensible** to Security/Legal.

---

## 8. Service authoring & deterministic run workflow *(the "notebook discipline", re-expressed)*

- **Strict module ordering, one responsibility per module.** `config.py` is the *only* home for
  constants/literals/`RULE_*` strings/lazy getters. No governance logic buried inside a tool —
  governance lives at the chokepoints named in §5. The layout in §2 is the dependency order.
- **The offline `pytest` suite is the "Restart & Run All" equivalent:** `make test` must run **clean,
  top to bottom, from a fresh checkout, with no network and no secrets**, and is **fully
  deterministic** — `RANDOM_SEED` seeds the `MockLLM` and any sampling; `rank_bm25` is deterministic;
  `DRAFT_TEMPERATURE = 0.0` in the live lane. Same input ⇒ same drafts, same confidence, same routing,
  every run. No hidden state between tests (fixtures reset lazy singletons).
- **The "backpack" is the only context the model sees.** `assemble_context` is the single place the
  prompt is built; nothing outside the retrieved chunks + the four declared layers reaches the model
  (`CTX1`). This bounds both context dilution and grounding leakage.
- **No dead/scratch code in the shipped tree** — no commented-out experiments, no unused branches, no
  `TODO`-only modules. What ships is what runs.
- **Every step is documented** — `README.md` narrates the run-from-clean-checkout; each module carries
  a top docstring stating its single responsibility and the `RULE_*` it enforces (if any).
- **TDD first.** For each module/tool the matching `QA_checklist.md` check is written before the code
  and must pass before the module is "done."
- **No magic values inline** — every number/threshold/literal/`RULE_*` is a named constant in §9 /
  `config.py`.

---

## 9. Stable names & conventions

```python
# --- retrieval (Stage 2) — rank_bm25, deterministic, paragraph/approved-answer chunks ---
RETRIEVAL_TOP_K              = 5         # chunks returned into the backpack (Recall-first; tune in Stage 2)
BM25_K1                     = 1.5       # rank_bm25 term-frequency saturation
BM25_B                      = 0.75      # rank_bm25 length normalization
RECALL_AT_K_TARGET          = 0.90      # acceptance bar for Recall@K on labeled fixtures (the MEASURED value lives in FACTS.md)

# --- confidence + routing (Stage 4) — hybrid: deterministic gate, LLM rationale only ---
CONFIDENCE_AUTO_THRESHOLD   = 0.75      # >= this AND no trigger → confident auto-draft (still needs human APPROVED)
CONFIDENCE_REVIEW_THRESHOLD = 0.50      # <  this → mandatory human review (RULE_HITM_REVIEW_TRIGGER)
GROUNDING_MIN_CITATIONS     = 1         # min retrieved chunks an asserted answer must cite (RULE_GROUNDED_ONLY)
GROUNDING_COVERAGE_MIN      = 0.5       # (added Stage 3, Asaf-flagged) min fraction of a draft's significant content tokens that must appear in the cited chunks; below → ungrounded
AMBIGUITY_SCORE_MARGIN      = 0.10      # top1−top2 BM25-score gap below this → "ambiguous" review trigger

# --- draft model (Stage 3; LIVE lane only — offline path uses MockLLM) ---
DRAFT_MODEL                 = "claude-sonnet-4-6"   # pin exact at Stage 1 (OQ-1); opus-4-8 swappable (graded contract)
MAX_OUTPUT_TOKENS           = 1024
DRAFT_TEMPERATURE           = 0.0       # determinism in the live lane

# --- determinism ---
RANDOM_SEED                 = 42        # seeds MockLLM + any sampling; the offline suite is reproducible

# --- routing / queues / tags (Stages 1 & 4) ---
REVIEWER_QUEUES             = ["security", "legal", "engineering", "gtm"]
DEFAULT_REVIEWER_QUEUE      = "engineering"  # (added Stage 4, Asaf-flagged) fallback queue when no item topic_tag maps to the routing_map; must ∈ REVIEWER_QUEUES
HIGH_RISK_TAGS              = ["legal", "security"]            # presence → mandatory routing
SENSITIVITY_TAGS            = ["public", "internal", "restricted"]   # internal/restricted never auto-export

# --- item state machine (Stage 4) ---
ITEM_STATES = ["INTAKE", "RETRIEVED", "DRAFTED", "SCORED",
               "ROUTED_FOR_REVIEW", "REVIEW_APPROVED", "REVIEW_REJECTED",
               "APPROVED", "EXPORTED"]

# --- byte-exact graded literals ---
REVIEW_BANNER          = "⚠️ PENDING HUMAN REVIEW — NOT APPROVED FOR EXTERNAL RELEASE"
UNGROUNDED_PLACEHOLDER = "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"

# --- the agent's callable functions (name == schema name == dispatch key) ---
AGENT_TOOLS = ["retrieve", "assemble_context", "draft_answer", "score_confidence",
               "route_for_review", "update_status", "write_audit", "export_response"]

# --- grep-enforceable governance identifiers (§5) — each is its own string value ---
RULE_GROUNDED_ONLY = "RULE_GROUNDED_ONLY"
RULE_NO_SELF_APPROVE = "RULE_NO_SELF_APPROVE"
RULE_HITM_REVIEW_TRIGGER = "RULE_HITM_REVIEW_TRIGGER"
RULE_NO_EXTERNAL_SEND = "RULE_NO_EXTERNAL_SEND"
RULE_SENSITIVITY_GATE = "RULE_SENSITIVITY_GATE"
RULE_NO_SECRET = "RULE_NO_SECRET"
RULE_NO_REAL_PII = "RULE_NO_REAL_PII"
RULE_NO_EVAL_CONTAMINATION = "RULE_NO_EVAL_CONTAMINATION"
RULE_NO_FABRICATED_METRIC = "RULE_NO_FABRICATED_METRIC"
RULE_AUDIT_COMPLETE = "RULE_AUDIT_COMPLETE"
RULE_SAFE_TERMINAL = "RULE_SAFE_TERMINAL"

# --- audit reason-codes (§5.1) — materialized as named constants as each stage needs them ---
GROUNDING_FAIL = "GROUNDING_FAIL"          # added Stage 3 (RULE_GROUNDED_ONLY chokepoint, app/draft.py)
ROUTED_HIGH_RISK = "ROUTED_HIGH_RISK"      # added Stage 4 (RULE_HITM_REVIEW_TRIGGER, app/routing.py)
ROUTED_AMBIGUOUS = "ROUTED_AMBIGUOUS"      # added Stage 4 (RULE_HITM_REVIEW_TRIGGER, app/routing.py)
ROUTED_LOW_CONFIDENCE = "ROUTED_LOW_CONFIDENCE"  # added Stage 4 (RULE_HITM_REVIEW_TRIGGER, app/routing.py)
SELF_APPROVE_BLOCKED = "SELF_APPROVE_BLOCKED"    # added Stage 4 (RULE_NO_SELF_APPROVE, app/state.py)
# (remaining §5.1 reason-codes — SENSITIVITY_HOLD, EXTERNAL_SEND_BLOCKED, ERROR_TERMINAL
#  — materialized at their stages 5–6)
```

- The LLM-provider interface (`LLMProvider`: `draft(context_stack) -> DraftAnswer`) is the **only** way
  out to a model — `MockLLM` (offline default) and `ClaudeLLM` (gated live) both implement it; the
  vendor is a swap behind it.
- Tool function name == schema name == dispatch key; a mismatch breaks dispatch — guard with an
  import-time `assert` over `AGENT_TOOLS`.
- Avoid vague names (`tmp`, `do_thing`). Helpers say what they do (`grounding_check`, `score_confidence`,
  `route_for_review`, `redact_pii`).
- **Confidence numbers are computed, never model-reported.** `confidence.py` derives the score from
  property validators (retrieval top-score, question coverage, grounding ratio); the LLM may write the
  *rationale string* only. (`CONF2`)

---

## 10. Non-negotiable quality rules (the short list)
1. **Import-safe.** No side effects, no client, no `.env`, no `data/*` read at import (§3, `ENV4`).
2. **No secrets in tracked files.** API key via env only (§5 `RULE_NO_SECRET`, `SEC1`/`LEAK1`).
3. **Grounded only.** No asserted answer without a cited retrieved chunk (`RULE_GROUNDED_ONLY`, `GROUND1`).
4. **The agent never self-approves.** Only a human transitions to `APPROVED`/`EXPORTED` (`RULE_NO_SELF_APPROVE`).
5. **No external send, ever.** Export is local-disk-only, post-approval (`RULE_NO_EXTERNAL_SEND`, `BOUND1`).
6. **Route the risky items.** High-risk tag / ambiguity / low confidence → human (`RULE_HITM_REVIEW_TRIGGER`).
7. **Inputs by name, validated, never hardcoded.** KB/questionnaire/tags from `data/*` (`KB1`/`DATA1`/`LEAK3`).
8. **Fail safe, never crash.** Component errors are data; failures end in a routed terminal (`RULE_SAFE_TERMINAL`).
9. **Deterministic offline suite.** `make test` is reproducible, seeded, network-free (`EVAL1`, §8).
10. **Every metric computed & audited.** No fabricated number; every transition logged (`RULE_NO_FABRICATED_METRIC`, `RULE_AUDIT_COMPLETE`).

---

## 11. Demo cases (assignment-mandated — both required, both graded)
- **Case 1 — confident auto-draft** (`data/questionnaires/case_confident.synthetic.json`): a question
  with strong KB coverage and no high-risk tag → high confidence, grounded draft, **no** routing
  trigger → presented as a confident draft still awaiting human `APPROVED` before export. (`DEMO1`)
- **Case 2 — human-review exception** (`data/questionnaires/case_review.synthetic.json`): a
  policy-sensitive / low-coverage question → a `RULE_HITM_REVIEW_TRIGGER` fires (high-risk tag and/or
  low confidence and/or ambiguity) → `ROUTED_FOR_REVIEW` to the correct queue with `REVIEW_BANNER`,
  never auto-included. (`DEMO2`)

---

## 12. Completion checklist (per stage — ticked before every handback)
- [ ] The module(s) for this stage run without errors.
- [ ] Every `QA_checklist.md` check referenced by this stage's DoD **passes** (run, not inspected).
- [ ] Import-safety holds (`ENV4` re-proven from an empty dir; lazy singletons `None`).
- [ ] No secret / real PII in any tracked file (grep clean — `SEC1`/`LEAK1`/`LEAK2`).
- [ ] Every `RULE_*` this stage touches has a live chokepoint + an audit reason-code + a passing QA ID.
- [ ] No hardcoded synthetic/real input values in code or prompts (`LEAK3`).
- [ ] Literals/thresholds byte-exact; offline suite still deterministic and green.
- [ ] Any number reported is verified against its source and recorded in `FACTS.md` (not restated elsewhere).
- [ ] Handback written to `handbacks/stage-<N>.md`; only a **pointer line** appended to `NOTES.md`.
- [ ] `PLAN.md` status ready for PM review (PM marks ✅, not the executer).

### 12.1 Claude Code handback format (append the payload to `handbacks/`, the pointer to `NOTES.md`)
1. **What changed** — modules/sections written vs drafted; new tests; files touched.
2. **DoD checklist** — each referenced QA ID ✅ / ⚠️; *drafted only* vs *written and test-verified*.
3. **QA results** — which check IDs were run and their pass/fail (salient output).
4. **Decisions made** — anything not explicitly specified (record in `NOTES.md`).
5. **DECISION-NEEDED** — any graded-contract change, open question, or secret → the **halt trigger**.
6. **Deviations / risks** — anything different from `PLAN.md`, with reason; unpinned deps, leakage doubt.
7. **Next recommended action** — one concrete next step only.

Do not silently advance to the next stage. Do not mark a stage ✅ on the executer's word — the PM
re-runs the checks itself, and re-runs any test the executer modified at the pre-edit revision
(verifier-independence, §0.1).
