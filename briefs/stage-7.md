# Brief — Stage 7: Offline eval harness + Option-A routing fix + confidence refactor

Read first (in order): `CLAUDE.md` (§5 `RULE_HITM_REVIEW_TRIGGER` / `RULE_NO_EVAL_CONTAMINATION` /
`RULE_NO_FABRICATED_METRIC`, §9) → `PLAN.md` (Stage 7) → `QA_checklist.md` (`EVAL1`–`EVAL3`,
`LEAK4`–`LEAK5`, `RET2`, plus `CONF1`–`CONF3` / `ROUTE1`–`ROUTE3` must stay green) → `NOTES.md`
(D-S7 + open follow-ups), then this brief.

Goal: implement Asaf's Option-A sensitivity routing, refactor confidence to remove the rationale
drift, build the offline eval harness (computed, held-out), and add `make eval`. Offline + deterministic.

## Scope — do ONLY this stage

### 0. `app/config.py` — NEW constants (Asaf-authorized graded additions; do NOT alter existing values)
- `REVIEWER_QUEUES` → append `"compliance"` → `["security", "legal", "engineering", "gtm", "compliance"]`.
- `SENSITIVITY_REVIEW_QUEUE = "compliance"` (must ∈ `REVIEWER_QUEUES`).
- `ROUTED_SENSITIVE = "ROUTED_SENSITIVE"` (the 4th `RULE_HITM_REVIEW_TRIGGER` reason-code).

### 1. `app/routing.py` — Option-A sensitivity trigger (graded; `RULE_HITM_REVIEW_TRIGGER`)
Add a **4th, lowest-precedence** trigger to `route_for_review` (keep the signature unchanged):
order = high-risk tag → ambiguity → low-confidence → **sensitivity**. If none of the first three fired
AND any chunk in `chunks` has `sensitivity ∈ {"internal", "restricted"}`:
  → `RoutingDecision(should_route=True, queue=SENSITIVITY_REVIEW_QUEUE, reason_code=ROUTED_SENSITIVE,
     rule=RULE_HITM_REVIEW_TRIGGER)`.
Otherwise unchanged (no trigger → `should_route=False`). Use a named constant for the restricted set
(reuse `export.py`'s `_RESTRICTED_SENSITIVITIES` pattern or define one in config — no inline literals).
This unblocks the export limbo: an internal/restricted item now routes → human REVIEW_APPROVED → export.

### 2. `app/confidence.py` — kill the rationale drift (graded; `CONF1`–`CONF3`)
Refactor so the coverage + retrieval_dominance values are computed **once** and reused by both the
score and the rationale string (eliminate the duplicate block in `score_confidence`). E.g. have
`_compute_score` return the three component values (or a small dataclass) alongside the score, and
build the rationale from those exact values. **The numeric score VALUE must NOT change** — CONF1–CONF3
stay green and the demo/Recall numbers are unchanged. The rationale must now match the scored
components exactly (no recomputation). Clears the deferred S4 follow-up.

### 3. `app/eval/harness.py` — offline evaluation harness (`EVAL1`–`EVAL3`, `LEAK4`–`LEAK5`)
> Path note: use `app/eval/harness.py` (the spine §2 path, consistent with the existing `app/eval/`
> package). (Asaf's brief wrote `app/eval_harness.py`; the PM is using the spine path — flagged.)
- Add a labeled held-out eval fixture set: `fixtures/eval/eval_cases.synthetic.json` — a list of cases,
  each: `{ "item_id", "question", "topic_tags": [...], "expected_routed": bool, "expected_queue": str|null,
  "expected_reason": str|null, "expected_grounded": bool }`. Cover the spectrum: a public confident
  case (not routed), a high-risk case (routed→legal/security), a low-coverage case (routed/low-conf),
  and an internal/restricted case (routed→compliance under Option A). **Synthetic; held out** (see §4).
- `def run_eval(*, retriever=None, provider=None, policy_tags=None) -> dict` computing, **all from the
  labeled fixtures (never hardcoded — `RULE_NO_FABRICATED_METRIC`/`LEAK5`):**
  - `recall_at_k` — reuse `app/eval/rubric.compute_recall_at_k` over `recall_at_k_gold.json`.
  - `grounding_rate` — fraction of eval cases whose draft passes `grounding_check` == matches
    `expected_grounded`, plus the raw grounded fraction.
  - `routing_accuracy` — fraction of eval cases whose `route_for_review` decision (should_route +
    queue + reason_code) matches the labeled expectation.
  - `calibration` — a small dict/matrix aligning confidence band (`confidence_band`) vs grounded
    outcome over the held-out cases (e.g. counts of auto/review × grounded/ungrounded).
- `make eval` target in the Makefile (`python -m app.eval.harness` or `python scripts/...`) that runs
  `run_eval` and prints the metrics; add to `.PHONY`. The PM records the numbers in `FACTS.md`.

### 4. Data isolation (`LEAK4`–`LEAK5`)
- The eval harness must **never mutate** the production KB (`data/kb/*`) or write into it; it reads the
  KB read-only and runs over the **held-out** eval fixtures. A test (`EVAL2`/`LEAK4`) proves the
  no-contamination guarantee — e.g. assert the eval-case questions are NOT present verbatim as KB chunk
  `question`s (the gold is not pre-seeded), AND that a deliberate contamination attempt (injecting a
  gold answer into a copy of the KB) is detectable / changes the metric. `LEAK5` = every metric traces
  to a computing function over labeled input (no hardcoded score).

### 5. Tests (`EVAL1`–`EVAL3`, `LEAK4`–`LEAK5`) + the affected existing tests + progressive ENV4
- Add NEW tests for the sensitivity trigger (ROUTE: an internal/restricted item with no higher trigger →
  routed to `compliance` / `ROUTED_SENSITIVE`; a public item unaffected) and for the eval harness.
- **EXISTING-test impact (Asaf-approved Option-A behavior change — update ONLY the expectation that
  reflects the new routing, document each change, change NOTHING else):**
  - `tests/test_stage6.py::test_demo1_i1_i2_not_routed` — under Option A, **i2 (internal) now routes to
    `compliance`**. Update this test to assert i1 NOT routed AND i2 routed→compliance/`ROUTED_SENSITIVE`
    (split/rename as needed); update the DEMO1 docstring at the top of the file accordingly.
  - `tests/test_stage4.py` ROUTE3 "benign not routed": run it; it should still pass IF its item's chunks
    are `public`. If (and only if) it now routes due to a sensitive chunk, that's the approved change —
    surface it in the handback (do not silently alter unrelated assertions).
  - **Do NOT touch any other existing test** (SEC*/RET*/CONF*/AUDIT*/EXPORT*/BOUND*/STATUS*/PIPE* and the
    rest of ROUTE*/DEMO*). If anything else goes red, STOP and surface DECISION-NEEDED.
- Add `app.eval.harness` to the ENV4-progressive test. Use `tmp_path` for any file writes.

## QA checks to PASS (run, not inspect): `EVAL1`–`EVAL3`, `LEAK4`–`LEAK5`, new sensitivity-routing tests; `RET2`/`CONF1`–`CONF3`/`ROUTE1`–`ROUTE3` stay green; `make test` green; `make eval` runs clean offline; `ENV4` clean.

## Constraints (from CLAUDE.md)
- Every metric computed from a labeled input (`RULE_NO_FABRICATED_METRIC`); held-out, no contamination
  (`RULE_NO_EVAL_CONTAMINATION`); the harness never mutates the production KB.
- Import-safe; deterministic offline; no inline magic values (queues/reason-codes/thresholds from §9).
- The confidence score VALUE is unchanged by the refactor.

## Do NOT
- Touch the spine docs (PM-owned). Adding the 3 config constants + new modules IS in scope; the PM syncs
  CLAUDE §9 + §5.1. Do NOT change any OTHER existing §9 value, schema field, byte-exact literal, or `RULE_*`.
- Modify ANY existing graded test EXCEPT the DEMO1 i2 expectation (and ROUTE3 only if genuinely affected)
  — and only to reflect the Asaf-approved Option-A routing. Adding new tests is fine. If anything else
  breaks, HALT as DECISION-NEEDED. Do not commit.
- Advance past Stage 7.

## Deliver
Write `handbacks/stage-7.md` (CLAUDE §12.1 format). Report: `make test` pass/skip count, the eval
metrics (recall_at_k, grounding_rate, routing_accuracy, calibration) from `make eval`, files
created/modified (call out the 3 new constants + the eval harness path + EXACTLY which existing tests
changed and how), confirmation the confidence score VALUE is unchanged + i2 now routes to compliance +
eval is held-out/computed, each `EVAL*`/`LEAK*` ✅/⚠️, any DECISION-NEEDED, one next action. Return it
as your final message. The PM re-runs everything, scrutinizes every existing-test diff (re-running at the
pre-edit revision), runs `/code-review`, and records the eval numbers in `FACTS.md`.
