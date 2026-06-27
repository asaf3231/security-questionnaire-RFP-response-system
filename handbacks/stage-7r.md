# Handback — Stage 7r: Honest Eval Governance Correction

Stage: **7r (governance re-do of rejected Stage 7)**
Executer: cold general-purpose subagent
Date: 2026-06-27

---

## 1. What Changed

### Files modified

| File | Change |
|---|---|
| `app/config.py` | Added `GROUNDING_QUESTION_COVERAGE_MIN = 0.30` (new §9 constant, D-S7r; in clean gap 0.111↔0.625) |
| `app/confidence.py` | Fixed npos==1 `retrieval_dominance`: now `= coverage` (not `1.0`). Rationale updated to use `components.retrieval_dominance` directly (no more stale top1/top2 recompute). Docstring updated. |
| `app/draft.py` | Added additive optional `question: str | None = None` param to `grounding_check()` and `draft_answer()`. When provided, enforces condition 4: `question_coverage < GROUNDING_QUESTION_COVERAGE_MIN` → ungrounded. When `None`, behaviour exactly as before (backward-compatible). |
| `app/pipeline.py` | Passes `item.question` to `draft_answer()` and `grounding_check()` in the per-item loop. |
| `app/eval/harness.py` | Deleted `_simulate_grounding` entirely. Updated imports (removed `GroundingResult`/`DraftAnswer`/`Citation`/`SENSITIVITY_REVIEW_QUEUE`; added `draft_answer`, `grounding_check`, `assemble_context`/`MockLLM` as lazy imports). `run_eval()` now calls real production grounding per case (assemble_context → draft_answer(question=…) → grounding_check(question=…)). Added idx counter for `assemble_context`. |
| `fixtures/eval/eval_cases.synthetic.json` | eval-006 set to honest negative: `expected_grounded=false`, `expected_routed=true`, `expected_reason="ROUTED_LOW_CONFIDENCE"`, `expected_queue="security"`. Rationalizing note replaced with accurate description. eval-003 and eval-005 untouched. |
| `tests/test_stage7.py` | `test_calibration_reflects_confidence_band_distribution`: replaced `_simulate_grounding` usage with real production path (assemble_context + draft_answer(question=…) + grounding_check(question=…)) to independently re-derive calibration. This is the only test that referenced `_simulate_grounding`; it now mirrors what `run_eval()` does. |

### New constant
`GROUNDING_QUESTION_COVERAGE_MIN = 0.30` in `app/config.py` — fraction of the question's significant tokens that must appear in the cited chunks' text. Clean gap: eval-006 qcov=0.111 < 0.30 ≤ 0.625 (minimum qcov across all legitimate items).

---

## 2. DoD Checklist

| QA ID | Status | Note |
|---|---|:---|
| EVAL1 | ✅ | All 4 metrics computed; run confirmed (see §5) |
| EVAL2 | ✅ | Held-out proven; contamination injection still raises |
| EVAL3 | ✅ | Calibration computed; review:ungrounded=1 (negative case honestly caught) |
| LEAK4 | ✅ | = EVAL2 |
| LEAK5 | ✅ | Perturb→changes (routing_accuracy changes); no fabricated metric |
| GROUND1 | ✅ | Existing grounding tests call without `question` → unaffected (315 passed) |
| CONF1–CONF3 | ✅ | Demo scores i1/i2/i3 = 0.799/0.861/0.880 (unchanged) |
| ROUTE1–ROUTE3 | ✅ | Routing correct; demo items routing unchanged |
| DEMO1 | ✅ | case_confident: i1 grounded/auto/not-routed; i2→compliance; i3→security |
| DEMO2 | ✅ | case_review: both items→legal (ROUTED_HIGH_RISK), grounded=True |
| PIPE1–PIPE2 | ✅ | Full suite green |

---

## 3. QA Results

### `make test` (full offline suite)
```
315 passed, 1 skipped
```
The 1 skip is the live-lane ClaudeLLM test (no ANTHROPIC_API_KEY in the offline suite) — unchanged from Stage 7.

### Tests changed and why
- **`tests/test_stage7.py::TestEVAL3::test_calibration_reflects_confidence_band_distribution`**:
  This test previously imported and used `_simulate_grounding` to independently re-derive the calibration. Since `_simulate_grounding` is deleted (the governance fix), the test was updated to use the real production path (assemble_context + draft_answer(question=…) + grounding_check(question=…)) — mirroring the new `run_eval()` implementation. This is the correct update: the independent verification now uses the same real logic. No assertion was weakened; the structural independence is preserved (the test still re-derives the calibration independently and asserts it matches `run_eval()`).

No other existing graded tests were modified.

---

## 4. Real eval-006 Outcome (from live pipeline — not from the harness's self-report)

```
n_positive_chunks: 1, scores: [1.045167516656759]
grounded: False
confidence score: 0.0741
confidence < CONFIDENCE_REVIEW_THRESHOLD (0.5): True
rationale: Confidence 0.074 = mean(coverage=0.111, grounded=0.0, retrieval_dominance=0.111). Retrieved 2 chunk(s); top BM25 score 1.0452; grounding gate: FAIL.
should_route: True
reason_code: ROUTED_LOW_CONFIDENCE
queue: security
```

**Honest acceptance confirmed:**
- `grounded=False` — driven by condition 4 (question_coverage=0.111 < GROUNDING_QUESTION_COVERAGE_MIN=0.30)
- `confidence score=0.0741 < CONFIDENCE_REVIEW_THRESHOLD=0.50` — driven by npos==1 fix (retrieval_dominance=coverage=0.111) + grounded=0.0
- `reason_code=ROUTED_LOW_CONFIDENCE`, `queue=security` — consistent with eval-006 gold
- Achieved by CODE, not gold-fitting

---

## 5. `make eval` Metrics

```
=== Comet Offline Eval Harness ===
Eval cases    : 6
Recall@K gold : 12 fixtures

recall_at_k       : 1.0000
grounding_rate    : match_rate=1.0000  raw_grounded=0.8333
routing_accuracy  : 1.0000

calibration (confidence_band × grounded outcome):
  auto    : grounded=5  ungrounded=0
  review  : grounded=0  ungrounded=1

Rules enforced: RULE_NO_FABRICATED_METRIC  RULE_NO_EVAL_CONTAMINATION
```

Key observations:
- `raw_grounded=0.8333` (5/6) — the negative case is now exposed (not 1.0 as before)
- `calibration review:ungrounded=1` — the negative case (eval-006) is in the review band and marked ungrounded
- `routing_accuracy=1.0000` — all 6 cases match their (now honest) gold labels
- `_simulate_grounding` deleted; grounding uses real `grounding_check(question=…)`

---

## 6. Proof Demo Items Unchanged

```
case_confident (pipeline run):
  q-confident-001-i1: score=0.799 grounded=True band=auto routed=False reason=None queue=None
  q-confident-001-i2: score=0.861 grounded=True band=auto routed=True reason=ROUTED_SENSITIVE queue=compliance
  q-confident-001-i3: score=0.880 grounded=True band=auto routed=True reason=ROUTED_HIGH_RISK queue=security

case_review (pipeline run):
  q-review-001-i1: score=0.848 grounded=True band=auto routed=True reason=ROUTED_HIGH_RISK queue=legal
  q-review-001-i2: score=0.963 grounded=True band=auto routed=True reason=ROUTED_HIGH_RISK queue=legal
```

All demo items are grounded. i1=0.799/i2=0.861/i3=0.880 are **identical to Stage 6 and Stage 7 values** (multi-chunk items, npos=5, npos==1 fix only touches eval-006).

---

## 7. Decisions Made

- `GROUNDING_QUESTION_COVERAGE_MIN = 0.30` (as suggested in the brief; fits cleanly in the 0.111↔0.625 gap). Surfaced to Asaf.
- Rationale was also updated to use `components.retrieval_dominance` directly (instead of recomputing top1/top2 ratio) — this is a consistency fix ensuring the rationale's reported value matches what was actually used in the score. The change is to the rationale string only (no score value affected, CONF2 intact).
- `SENSITIVITY_REVIEW_QUEUE` import removed from `harness.py` (it was only used in the deleted `_simulate_grounding`).

---

## 8. DECISION-NEEDED

None. All 4 fixes in the brief are implemented. No graded contract was changed (only the additive `GROUNDING_QUESTION_COVERAGE_MIN` constant added, as directed). No spine files touched.

---

## 9. Deviations / Risks

- None. The implementation follows the brief exactly.
- The rationale consistency fix (using `components.retrieval_dominance` instead of recomputing) is a quality improvement, not a contract change; no test asserts the specific `rd_val` value in the rationale string.
- `harness.py` now calls `assemble_context` and `MockLLM` — these are lazy imports inside `run_eval()`, preserving import-safety.

---

## 10. Next Recommended Action

PM independently runs `make test` and the real pipeline on eval-006 (to confirm `grounded=False` and `ROUTED_LOW_CONFIDENCE` by CODE, not gold-fitting), then marks Stage 7r ✅ and advances to Stage 8.
