# Brief — Stage 1: Environment, secrets, config & synthetic inputs

Read first (in order): `CLAUDE.md` → `PLAN.md` (Stage 1) → `QA_checklist.md` (§0–§3, the IDs below) →
`NOTES.md` (decisions D-1..D-7, OQ-1/OQ-2 resolved), then this brief.

Goal: Stand up a clean, **import-safe** repo — pinned deps, env/ignore/Makefile/README, the config
module (the single home for §9 constants + `RULE_*` strings + lazy Claude getter), the Pydantic
schema, the KB/questionnaire/policy **load + validate** layer, and the bounded **synthetic** data —
before any retrieval, draft, or routing logic.

## Scope — do ONLY this stage
Create exactly these, matching `CLAUDE.md` §1/§2/§4/§9:

1. **`requirements.txt`** — pin **every** non-stdlib import with `==` at the exact version you install
   in the venv: `pydantic`, `rank_bm25`, `anthropic`, `python-dotenv`, `pytest`. (Create the venv,
   install latest stable of each, then `pip freeze` the exact `==` versions for these + any required
   transitives your code imports. `os/sys/json/re/csv/math/time/random/pathlib/dataclasses/datetime/
   enum/hashlib/importlib/typing` are stdlib — do NOT list them.)
2. **`.env.example`** — `ANTHROPIC_API_KEY=` placeholder only. **No real key anywhere.**
3. **`.gitignore`** — `.env`, `.venv/`, `exports/`, `audit/`, `__pycache__/`, `*.pyc`, `.DS_Store`,
   and any real/customer data. (`.DS_Store` is currently tracked — also run `git rm --cached .DS_Store`
   so the ignore takes effect; mention it in the handback.)
4. **`Makefile`** — a working **`test`** target (`pytest -q`) and an **`install`** target
   (`pip install -r requirements.txt`). Do **not** add `demo`/`demo-live`/`eval` targets yet — those
   land when their code lands (no dead/TODO-only targets; `CLAUDE.md` §8). The README notes they arrive
   in later stages.
5. **`README.md`** — the run-from-clean-checkout path (`CLAUDE.md` §1): venv → `pip install` →
   `cp .env.example .env` → `make test`. State clearly that `make demo`/`make demo-live`/`make eval`
   arrive in later stages, and that the data is **synthetic/fake** (state assumptions).
6. **`app/__init__.py`** (empty) and **`app/config.py`** — the ONLY home for magic values. Copy the
   §9 block from `CLAUDE.md` **verbatim** (constants, `REVIEWER_QUEUES`, `HIGH_RISK_TAGS`,
   `SENSITIVITY_TAGS`, `ITEM_STATES`, `AGENT_TOOLS`, all 11 `RULE_*` string constants, the two
   byte-exact literals `REVIEW_BANNER` / `UNGROUNDED_PLACEHOLDER`, `DRAFT_MODEL="claude-sonnet-4-6"`).
   Add: an import-time `assert` that every `AGENT_TOOLS` name is unique; a lazy `_get_claude()`
   singleton (module-global `None`, constructed only on first call, never at import) and a
   `load_env()` helper that calls `dotenv` **inside the function, never at import**. **Nothing at
   import time may** read `.env`, build a client, read `data/*`, or touch the network.
7. **`app/schema.py`** — Pydantic models (import-safe, no side effects): `QuestionnaireItem`
   (`item_id`, `question`, `topic_tags: list[str] = []`), `RetrievedChunk`, `ContextStack`
   (4 layers: instruction/retrieval/constraint/state), `Citation`, `DraftAnswer`
   (`text`, `citations: list[Citation]`), `ConfidenceResult` (`score: float`, `rationale: str`),
   `RoutingDecision`, `AuditEvent` (`timestamp`, `questionnaire_id`, `item_id`, `event`,
   `from_state`, `to_state`, `rule`, `detail: dict`), `ResponseDoc`. Define them fully now even though
   later stages populate them; validators raise on malformed input.
8. **`app/kb.py`** — **load + validate ONLY** (NO ranking — that is Stage 2). Loaders that read the
   `data/*` files **by name** (build paths with `pathlib` relative to repo root) and validate via the
   schema: `load_kb()`, `load_questionnaire(path)`, `load_policy_tags()`. **`KB1`/`DATA1` are strict
   (Asaf): a missing/renamed required field raises a clean explicit `ValueError` (never a later
   `KeyError`); `sensitivity` must be ∈ `SENSITIVITY_TAGS`; only `approved==True` chunks are marked
   retrievable; the policy routing map may reference only `REVIEWER_QUEUES`.** No value from `data/*`
   is hardcoded into code (`KB2`/`LEAK3`).
9. **Synthetic data** (`data/…`, all `*.synthetic.*`, fake — state assumptions in `README.md`):
   - `data/kb/approved_answers.synthetic.json` — a bounded set (~12–20) of prior **approved** Q&A
     chunks: `chunk_id`, `question`, `answer`, `source`, `sensitivity ∈ {public,internal,restricted}`,
     `topic_tags[]`, `approved`. Include ≥1 `internal`/`restricted`, ≥1 `approved=False`
     (non-retrievable), and varied `topic_tags` (e.g. infrastructure, data-handling, compliance,
     security, legal). **Design for the two demo cases:**
       • strong, `public`, non-high-risk coverage for **case_confident**'s topic;
       • for **case_review**: either no good coverage, or the only relevant chunk is
         `restricted`/`internal` and/or carries a high-risk (`legal`/`security`) topic.
   - `data/kb/docs/` — 2–4 short product/security doc paragraphs (one paragraph = one chunk), tagged.
   - `data/questionnaires/case_confident.synthetic.json` — one questionnaire, ≥1 item whose question
     is well-covered by a `public` approved answer, non-high-risk `topic_tags`.
   - `data/questionnaires/case_review.synthetic.json` — one questionnaire, ≥1 item that is
     policy-sensitive (high-risk tag) and/or low-coverage → will trip a review trigger later.
   - `data/policy_tags.synthetic.json` — defines `SENSITIVITY_TAGS`, `HIGH_RISK_TAGS`, and the
     tag→reviewer-queue routing map (queues ⊆ `REVIEWER_QUEUES`). (These mirror §9 values but live in
     data so they are loaded+validated, not hardcoded in tools.)
10. **`tests/`** — offline, deterministic, network-free, no `.env`. Write the checks **test-first**
    and make them pass:
    - `ENV4` — import every `app.*` module that exists after this stage (`app.config`, `app.schema`,
      `app.kb`) from a clean process; assert zero side effects (lazy singleton is `None` until called;
      no `.env` read; no `data/*` read at import).
    - `KB1` — valid KB loads; a KB missing a required field / bad `sensitivity` raises `ValueError`;
      `approved==False` chunks are not retrievable.
    - `DATA1` — questionnaires + policy_tags load + validate; routing map references only
      `REVIEWER_QUEUES`; a malformed questionnaire raises `ValueError`.
    - config checks — the two byte-exact literals equal `CLAUDE.md` §9; `AGENT_TOOLS` unique;
      all 11 `RULE_*` constants present; `DRAFT_MODEL == "claude-sonnet-4-6"`.
    - `KB2` — grep-style test: no `data/*` answer/question/source/routing literal appears in `app/`.
    - a `SEC1` test (or `scripts/`): the git-tracked set contains no `sk-ant-`/`ANTHROPIC_API_KEY=`
      value (placeholders in `.env.example` are fine).

## QA checks to PASS (run, not inspect): `ENV1`, `ENV2`, `ENV3`, `ENV4`, `SEC1`, `SEC2`, `KB1`, `KB2`, `DATA1`
Run `make test` and confirm green. Re-prove `ENV4` from an empty cwd.

## Constraints (from CLAUDE.md — the ones that bite this stage)
- **Import-safe** (`ENV4`): zero side effects at import — no client, no `.env`, no `data/*` read, no
  network, no file write. Lazy singletons only.
- **No secret in any tracked file** (`RULE_NO_SECRET`/`SEC1`): key via env only.
- **No hardcoded input values** (`RULE_NO_REAL_PII`/`KB2`/`LEAK3`): `data/*` loaded by name.
- **Strict validation** (`KB1`/`DATA1`): malformed input → explicit `ValueError`, not `KeyError`.
- **Determinism / no dead code** (`CLAUDE.md` §8): seeded where relevant; no commented-out or
  TODO-only scaffolding.
- **Constants/literals byte-exact** to `CLAUDE.md` §9 — `config.py` is the only place they live.

## Do NOT
- Implement retrieval ranking (`rank_bm25` scoring), the context-stack assembler, drafting, confidence,
  routing, state machine, audit, export, pipeline, or eval — those are Stages 2–7.
- Change any graded contract (a §9 constant value, a `RULE_*` id, a schema field name, a byte-exact
  literal). If something seems wrong, surface it as **DECISION-NEEDED**, do not change it.
- Advance past Stage 1.

## Deliver
Write `handbacks/stage-1.md` in the `CLAUDE.md` §12.1 format (What changed / DoD checklist with each QA
ID ✅-or-⚠️ and *drafted* vs *test-verified* / QA results with the salient `make test` output /
Decisions made / DECISION-NEEDED / Deviations+risks / one Next action). Return it as your final message.
Report the exact `make test` pass/skip count and the pinned dependency versions (the PM records numbers
in `FACTS.md` after re-running).
