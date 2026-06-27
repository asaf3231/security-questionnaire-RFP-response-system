# Stage 7 Handback — Offline eval harness + Option-A routing fix + confidence refactor

Date: 2026-06-27
Executer: general-purpose subagent (cold)

---

## 1. What changed

### Files created
- `app/eval/harness.py` — `run_eval()` computing all four metrics from held-out fixtures; `__main__` CLI; `check_no_contamination()` proving EVAL2/LEAK4; `_simulate_grounding()` (deterministic, no LLM); `_ScoreComponents` carrier (unused externally).
- `fixtures/eval/eval_cases.synthetic.json` — 6 held-out labeled cases covering: public confident (not routed), legal high-risk (ROUTED_HIGH_RISK), legal+security high-risk (ROUTED_HIGH_RISK), encryption/internal (ROUTED_SENSITIVE), compliance/internal (ROUTED_SENSITIVE), weak-coverage mid-band (not routed, review band). Questions rephrased from KB chunk questions to guarantee held-out status (RULE_NO_EVAL_CONTAMINATION).
- `tests/test_stage7.py` — 36 new tests: TestENV4Stage7 (3), TestSensitivityRouting (8), TestEVAL1 (8), TestEVAL2 (4), TestEVAL3 (3), TestConfidenceRefactor (3), TestStage7ConfigConstants (6).

### Files modified
- `app/config.py` — 3 new §9 constants added (Asaf-authorized):
  - `REVIEWER_QUEUES` appended with `"compliance"` → `["security", "legal", "engineering", "gtm", "compliance"]`
  - `SENSITIVITY_REVIEW_QUEUE = "compliance"` (must ∈ REVIEWER_QUEUES)
  - `ROUTED_SENSITIVE = "ROUTED_SENSITIVE"` (4th RULE_HITM_REVIEW_TRIGGER reason-code)
- `app/routing.py` — 4th (lowest-precedence) sensitivity trigger added: if any chunk `sensitivity ∈ {internal, restricted}` and triggers 1–3 did not fire → `RoutingDecision(should_route=True, queue=SENSITIVITY_REVIEW_QUEUE, reason_code=ROUTED_SENSITIVE, rule=RULE_HITM_REVIEW_TRIGGER)`. Module-level `_SENSITIVE_VALUES = frozenset({"internal", "restricted"})` constant (no inline literal). Signature unchanged. Docstring updated to list 4 triggers.
- `app/confidence.py` — Stage 7 refactor: `_compute_components()` is the new single source of truth for coverage + retrieval_dominance + grounded_val; `_compute_score()` delegates to it (still returns float — backward compat); `score_confidence()` calls `_compute_components()` and reuses the exact component values for the rationale. `_ScoreComponents` frozen dataclass introduced. Score VALUE is unchanged (same formula, same inputs, same weights). CONF1–CONF3 all green.
- `app/eval/fixtures.py` — Added a filter to skip `eval_cases.synthetic.json` (Stage 7 eval-cases schema ≠ recall@K schema). `load_eval_fixtures()` now only loads files whose name is not `eval_cases.synthetic.json`.
- `Makefile` — Added `eval` target (`python -m app.eval.harness`) and added `eval` to `.PHONY`.

### Existing tests changed

**Authorized changes (Asaf-approved Option-A behavior + graded REVIEWER_QUEUES addition):**

1. `tests/test_stage1.py::TestConfigConstants::test_reviewer_queues`
   - Changed: `assert == ["security", "legal", "engineering", "gtm"]` → `assert == ["security", "legal", "engineering", "gtm", "compliance"]`
   - Reason: Asaf-authorized graded addition of "compliance" to REVIEWER_QUEUES (D-S7). Mechanical reflection of the approved constant change, not a weakening.

2. `tests/test_stage6.py::TestDEMO1` — three changes:
   - `test_demo1_i1_i2_not_routed` **renamed/split** into two tests:
     - `test_demo1_i1_not_routed` — asserts i1 NOT routed (unchanged behavior, public chunks only)
     - `test_demo1_i2_routed_compliance` — asserts i2 routed to `compliance`/`ROUTED_SENSITIVE` (new Option-A behavior: i2 retrieves kb-009 with `sensitivity=internal`)
   - `test_demo1_rule_hitm_not_fired_for_i1_i2` → `test_demo1_rule_hitm_not_fired_for_i1` — now checks only i1 in the audit log (i2 now fires RULE_HITM_REVIEW_TRIGGER via ROUTED_SENSITIVE)
   - `TestDEMO1` class docstring updated to document Option-A behavior
   - `test_demo1_i1_i2_grounded_drafts` docstring updated to clarify that i2 is still grounded before routing (no assertion change)

---

## 2. DoD checklist

| QA ID | Status | Notes |
|-------|--------|-------|
| EVAL1 | ✅ | 8 tests; all four metrics computed from labeled fixtures; no hardcoded score |
| EVAL2 | ✅ | 4 tests; contamination detected and rejected; KB not mutated; data/ not written |
| EVAL3 | ✅ | 3 tests; calibration derived independently from scoring loop; both bands exercised |
| LEAK4 | ✅ | = EVAL2; verified by contamination injection test |
| LEAK5 | ✅ | = EVAL1; perturb test proves metrics change with fixture change |
| RET2  | ✅ | Unchanged; still green; Recall@K = 1.0000 |
| CONF1–3 | ✅ | Refactor unchanged score VALUE; float return; all 27 CONF tests green |
| ROUTE1–3 | ✅ | All 15 ROUTE tests green; existing benign ROUTE3 test uses public chunks → unaffected |
| ENV4  | ✅ | 3 new tests; app.eval.harness imports without side effects |

---

## 3. QA results

**`make test`:** 315 passed / 1 skipped (vs 278/1-skip baseline — 37 new tests total including Stage 7)
**`make eval`:**
```
recall_at_k       : 1.0000
grounding_rate    : match_rate=1.0000  raw_grounded=1.0000
routing_accuracy  : 1.0000
calibration:
  auto    : grounded=5  ungrounded=0
  review  : grounded=1  ungrounded=0
n_eval_cases      : 6
n_recall_gold     : 12
```

---

## 4. Decisions made

- **`_compute_score()` kept as float-returning** (backward-compat): the existing Stage-4 tests call `_compute_score()` and compare as a float — changing its return type would require modifying graded tests. Instead, `_compute_components()` is the new internal source of truth; `_compute_score()` delegates to it and returns `.score`. The refactor goal (eliminate drift) is achieved.
- **`eval_cases.synthetic.json` questions rephrased** from KB chunk questions: eval-003 was an exact match for kb-016's question; rephrased to "What indemnification provisions apply if a security breach originates from your platform?" to satisfy `RULE_NO_EVAL_CONTAMINATION`.
- **`load_eval_fixtures()` updated** to skip `eval_cases.synthetic.json` (different schema from recall@K fixtures); the filter is conservative: only the exact filename is excluded.
- **6 eval cases** (not the minimum 4 from the brief): added an extra high-risk case and a weak-coverage mid-band case to give the calibration matrix non-trivial coverage in both bands.
- **`test_stage1.py::test_reviewer_queues` updated** as a mechanical reflection of the Asaf-authorized graded change to REVIEWER_QUEUES; this is the only Stage-1 test modified.

---

## 5. DECISION-NEEDED

None. All changes are within the Asaf-authorized scope (D-S7). No graded contract was altered beyond the three authorized additions.

---

## 6. Deviations / risks

- None. The confidence score VALUE is confirmed unchanged (CONF1–3 green, 315/1 suite clean).
- i2 now routes to `compliance`/ROUTED_SENSITIVE as Asaf intended (Option A).
- Eval is held-out: `check_no_contamination()` passes for all 6 fixtures; KB files are not mutated.
- All metrics computed from labeled inputs: perturb test confirms routing_accuracy changes when fixture labels are flipped.
- `ROUTE3` benign test (`test_high_confidence_no_high_risk_no_ambiguity_not_routed`) uses chunks with `sensitivity="public"` → sensitivity trigger does not fire → still passes unchanged.

---

## 7. Next recommended action

Stage 8 — Anti-leakage & packaging hardening: run `/security-review` as the governance gate; verify all seven `LEAK*` cross-checks green; harden `.gitignore`/README/docstrings; add one tracked redacted sample export + audit log. Pre-condition: PM marks Stage 7 ✅ after re-running `make test` + `make eval` and recording the eval numbers in `FACTS.md`.
