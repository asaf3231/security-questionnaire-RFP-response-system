# HANDOFF.md — Fresh-PM Handoff · Reindeer "Comet" RFP/Security-Questionnaire Agent

> Curated single-document handoff for a **fresh PM taking over cold** (per
> `PM_Methodology_Prompt.md` → Session Continuity). **Regenerated 2026-06-28** after the
> "close all loose edges" reconciliation session.
> **`STATE.md` remains the one-screen resume primitive; this file is the fuller narrative.**
> Every hard number lives in `FACTS.md` — treat numbers here as a *re-verify-me snapshot*, not authority.

---

## 0. Read this, in this order, before doing anything
1. `PM_Methodology_Prompt.md` — your role, budget rules, memory architecture, the **Session
   begin/end ritual**.
2. `STATE.md` — the checkpoint (current stage, resume action, live-truth snapshot).
3. `CLAUDE.md` — the **authoritative rulebook** (env, §5 `RULE_*` governance registry incl. §5.3
   `RULE_GRADED_ARTIFACT_LOCK` / `RULE_METRIC_FALSIFIABLE`, §9 constants + byte-exact literals).
4. `PLAN.md` — stage tracker (0–10) with per-stage DoD → `QA_checklist.md` IDs.
5. `FACTS.md` — the ONLY home for verified numbers.
6. `NOTES.md` — decisions (the *why*) + handback pointers + open follow-ups.
7. `PM_LOG.md` (latest entry) + `PM_LOG_archive.md` / `NOTES_archive.md` (history; **not** read on resume).

---

## 1. Current state — where the project is
- **Branch:** `redteam/crazy-testing` (NOT `main`). It adds an ADD-only adversarial red-team layer
  (`tests/test_redteam.py`) + Stage 10 (Intelligent Query Refinement) on top of `main`'s Stage 0–8.
- **Stages 0–8 ✅** (committed on `main`, tags `stage-0-spine` … `stage-8-packaging`).
- **Stage 10 ✅** (Intelligent Query Refinement) — implemented, `/code-review`'d, Asaf-signed-off, and
  reconciled on `redteam/crazy-testing` (2026-06-28). The draft `<thinking>` scaffold was **removed**
  per live evidence (it tanked live grounding); the refine-query `<thinking>` + a defensive draft-strip
  remain. See `briefs/stage-10.md` + `handbacks/stage-10.md`.
- **Stage 9 (Brief/Deck + Technical Appendix) ✅ authored** 2026-06-28 — `brief/REINDEER_BRIEF.md` +
  `appendix/TECHNICAL_APPENDIX.md` (every number traces to `FACTS.md`).
- The agent ("Comet") is a complete, runnable, offline-deterministic service: questionnaire →
  intake → **refine query** → retrieve → assemble context → draft → grounding-gate → confidence →
  route → state → audit → export, human-in-the-loop, no external send.

**Verified snapshot (re-verify via `FACTS.md` source-of-truth commands):**
- Offline suite: **569 pass / 1 skip / 2 xfail** via `make test` (skip = live-gated `DRAFT2`; 2 xfail =
  documented lexical-grounding limits in the red-team suite).
- Eval (`make eval`): recall@K **1.0**, routing_accuracy **1.0**, grounding match **1.0** / raw_grounded
  **0.833** (the negative case eval-006 honestly ungrounded), calibration exposes the negative case.
- Demo: i1 0.799 (auto→exported), i2 0.861 (ROUTED_SENSITIVE→compliance), i3 0.880
  (ROUTED_HIGH_RISK→security), case_review→legal (not exported).
- 17 `app/` modules (incl. `app/query_optimizer.py`), 20-chunk synthetic KB.

---

## 2. Standing rules (do not break)
- `tests/` + `fixtures/` are **ADD-ONLY** (`RULE_GRADED_ARTIFACT_LOCK`). Modifying/deleting an existing
  one needs **two-key** human authorization (`ALLOW_GRADED_EDIT=1`, a human-only key) + a pre-edit re-run.
- Numbers live **only** in `FACTS.md`; every other file references them by name.
- Governance is **code-enforced** (`RULE_*` chokepoints), never prompt-enforced. The in-`<thinking>`
  self-checks are defense-in-depth UX only.
- Live grounding is materially lower than offline mock grounding — **expected**: when the live model
  omits inline `[chunk_id]` citations the grounding gate forces `UNGROUNDED_PLACEHOLDER` + human review.

---

## 3. Open / watch
- The live lane (`make demo-live`, `make chat-live`, `scripts/run_live_suite.py`) is the only path that
  calls the Claude API; still no external send. Live token spend is not recorded (optional).
- Untracked operational/evidence files: `redteam/LIVE_RUN_FINDINGS*.md`, `crazy_test_prompt.md`,
  `scripts/run_chat.py`, `scripts/run_live_suite.py` — decide with Asaf whether to commit as evidence.
- Native `/security-review` CLI needs a git `origin` remote (none configured) — a manual equivalent scan
  ran CLEAN at Stage 8.

---

## 4. Fix log (this session, 2026-06-28)
- Working tree was RED (uncommitted `app/llm.py` removed the draft `<thinking>` directive) → kept the
  removal (live evidence), two-key retired 2 draft-COT tests, suite green.
- Fixed `strip_thinking_block` nested-tag leak + a token-fusion regression (depth-aware scan, `/code-review`).
- Moved 2 magic numbers to `config.py` §9; added `refine_query` audit `to_state`; dropped unused imports;
  `run_chat.py` argparse → stdlib (it broke ENV2).
- Reconciled FACTS/STATE/PLAN/QA/CLAUDE/README/NOTES; tombstoned the ghost "Stage 10/11 KB-expansion".
