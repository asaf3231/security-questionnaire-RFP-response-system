# Stage 8 Handback — Anti-Leakage & Packaging Hardening

**Executer:** cold `general-purpose` agent
**Date:** 2026-06-27
**Stage:** 8 — Anti-leakage & Packaging Hardening
**Stage boundary:** NOT advanced past Stage 8.

---

## 1. What changed

### Files created (ADD-only)
- `pyproject.toml` — minimal package metadata, `requires-python >= 3.11`, packages = `app` + `app.eval`, explicit excludes for `tests/`, `fixtures/`, `data/`, `scripts/`, `handbacks/`, `briefs/`, `brief/`, `appendix/`; `[tool.pytest.ini_options] testpaths = ["tests"]`
- `samples/q-confident-001.sample.md` — redacted export Markdown (machine-local path + timestamps replaced with `[REDACTED-*]` placeholders; all content synthetic)
- `samples/q-confident-001.sample.csv` — redacted export CSV grid
- `samples/q-confident-001.sample.jsonl` — redacted audit JSONL (24 events covering the full pipeline trace for case 1 item 1)
- `fixtures/eval/PROVENANCE.md` — gold-case provenance for all 6 eval cases; derived from spec/intent/rules, NOT from observed output (META-PROVENANCE lock-safe ADD)
- `tests/test_stage8.py` — 58 NEW tests covering PKG1–3, LEAK1–LEAK-S, SEC2, META-FALSIFY, META-REALPATH, META-PROVENANCE

### Files modified (no existing tests or fixtures touched)
- `Makefile` — added `PY := .venv/bin/python`, `PYTEST := .venv/bin/pytest`, `check_venv` guard macro; all python/pytest invocations use `$(PY)`/`$(PYTEST)`; `make eval` uses `$(PY) -m app.eval.harness`; integrity pre-flight and `test: integrity` / `eval: integrity` dependencies KEPT UNCHANGED
- `.gitignore` — added a comment block documenting that `samples/` is a TRACKED directory (so it won't accidentally be gitignored); removed duplicate `*.egg-info/`/`dist/`/`build/` entries (they were already present earlier in the file)
- `README.md` — added "Package boundary + run-from-clean-checkout" section documenting what ships vs dev-only, the venv-clean one-command path, the integrity pre-flight, and the governance boundary

### Files NOT touched
- `app/` — no modifications; no debug/print/breakpoint/TODO/FIXME found outside the legitimate eval harness `print()` report output
- All existing `tests/test_stage*.py` — ADD-ONLY (not modified, not deleted)
- All existing `fixtures/eval/*.json` — ADD-ONLY (not modified, not deleted)
- All `app/config.py` constants, schema fields, byte-exact literals, `RULE_*` strings — unchanged

---

## 2. DoD checklist

| QA ID | Check | Status |
|---|---|---|
| `PKG1` | Clean-checkout shape: venv-clean Makefile, `pyproject.toml`, `samples/` present | ✅ Tested in `TestPKG1` (13 tests) |
| `PKG2` | `.gitignore` correctness via `git check-ignore` | ✅ Tested in `TestPKG2` (9 tests) |
| `PKG3` | README package-boundary section + all `app/` modules have top docstrings | ✅ Tested in `TestPKG3` (5 tests) |
| `LEAK1` | No secret (sk-ant- / ANTHROPIC_API_KEY=) in any tracked file | ✅ `TestLEAK1` + already covered by existing `test_stage1.py::TestSEC1` |
| `LEAK2` | No real email/PII in tracked data files; only `*.synthetic.*` tracked | ✅ `TestLEAK2` (2 tests) |
| `LEAK3` | No KB answer text / chunk IDs hardcoded in `app/` | ✅ `TestLEAK3` (2 tests) |
| `LEAK4` | Eval contamination guard: `check_no_contamination` present + injection raises `ValueError` | ✅ `TestLEAK4` (3 tests) |
| `LEAK5` | All metrics computed (not hardcoded): rubric does arithmetic; `run_eval()` returns floats in [0,1] | ✅ `TestLEAK5` (4 tests) |
| `LEAK-G` | Grounding gate: fabricated / no-citation drafts → `UNGROUNDED_PLACEHOLDER` byte-exact | ✅ `TestLEAKG` (4 tests) |
| `LEAK-S` | Sensitivity gate: `internal` item held from export without `REVIEW_APPROVED` | ✅ `TestLEAKS` (3 tests, including a live export assertion) |
| `SEC1` | Already covered by `test_stage1.py::TestSEC1` | ✅ Pre-existing |
| `SEC2` | No secret + no machine-local paths in `samples/` | ✅ `TestSEC2` (2 tests) |
| `META-LOCK` | Integrity pre-flight passes; no modification/deletion in `tests/`+`fixtures/` | ✅ `make test` + `make eval` both ran through `check_graded_artifacts.sh` without error |
| `META-FALSIFY` | Eval gold has ≥1 negative case (`expected_routed=true`, `expected_grounded=false`) | ✅ `TestMetaFalsify` (4 tests) |
| `META-REALPATH` | No `def _simulate_*` in `app/`; harness calls real `grounding_check` + `draft_answer` | ✅ `TestMetaRealpath` (3 tests) |
| `META-PROVENANCE` | `fixtures/eval/PROVENANCE.md` exists; covers all 6 eval case IDs; references spec/rules | ✅ `TestMetaProvenance` (3 tests) |

---

## 3. QA results

### `make test` (via venv-clean Makefile)
```
bash scripts/check_graded_artifacts.sh
[RULE_GRADED_ARTIFACT_LOCK] OK: no unauthorized modification/deletion in the locked set (tests fixtures).
.venv/bin/pytest -q
373 passed, 1 skipped in 2.13s
```

Baseline was 315 passed / 1 skipped. Stage 8 adds 58 new tests → **373 passed / 1 skipped**. The 1 skip is the pre-existing live-lane (`DRAFT2`) test.

### `make eval` (via venv-clean Makefile)
```
bash scripts/check_graded_artifacts.sh
[RULE_GRADED_ARTIFACT_LOCK] OK: no unauthorized modification/deletion in the locked set (tests fixtures).
.venv/bin/python -m app.eval.harness

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

All metrics unchanged from Stage 7r (Recall@K 1.0, routing_acc 1.0, calibration has negative case). Green.

---

## 4. Decisions made

- **`samples/` directory name** — used `samples/` as the new tracked dir for redacted outputs (brief: "e.g. `samples/`"). Three files: `.md`, `.csv`, `.jsonl` covering all three output types.
- **LEAK-G test API** — `grounding_check()` returns `GroundingResult.answer` (a `DraftAnswer`) not `.text` directly; tests assert on `result.answer.text`.
- **`tempfile` import removed** — ENV2 scanner (existing `test_stage1.py`) would flag `import tempfile` as unpinned. Used pytest's `tmp_path` fixture instead (no import needed).
- **LEAK4 test approach** — the harness's `check_no_contamination(cases, chunks)` is a public function that raises `ValueError` on verbatim-question contamination. Test calls it directly with an injected verbatim KB question. This is more surgical than calling `run_eval()` with injected args (which the API doesn't support).
- **`pyproject.toml` note** — `[build-system]` uses `setuptools.backends.legacy:build` which is valid for `setuptools >= 68`. No `setuptools` pin needed in `requirements.txt` as it's only a build-time dep.
- **`samples/` note in `.gitignore`** — added a comment documenting that `samples/` is intentionally tracked and must NOT be gitignored; removed accidental duplicate `*.egg-info/`/`dist/`/`build/` block.

---

## 5. DECISION-NEEDED

None. No graded contracts were changed. No §9 constants, schema fields, byte-exact literals, `RULE_*` strings, confidence thresholds, routing tables, or audit-event schema were modified.

---

## 6. Deviations / risks

- **No deviations from `PLAN.md` Stage 8 scope.** All four requirements delivered: (a) venv-clean Makefile, (b) anti-leakage hardening, (c) packaging + samples, (d) new `tests/test_stage8.py`.
- **`samples/` not yet git-tracked**: files exist in `samples/` but are untracked (git untracked) since we did not commit. The `TestPKG1::test_samples_dir_exists_with_files` test checks for file existence (not git tracking), which is correct at this point. After Asaf's `git add samples/ && git commit`, the test will also pass a stricter git-tracked check if needed.
- **Print statements in `app/eval/harness.py`** — the `print()` calls in that file are legitimate structured CLI output for the eval report (not debug artifacts). Removed no code.
- **ALLOW_GRADED_EDIT: never set** — confirmed `echo $ALLOW_GRADED_EDIT` = `<not set>` throughout.

---

## 7. Confirm add-only for graded artifacts

```
git diff HEAD -- tests/ fixtures/
(empty — zero modifications/deletions)
```

`check_graded_artifacts.sh` ran successfully (exit 0) at every `make test` and `make eval` invocation. No existing test file or fixture was modified or deleted. `tests/test_stage8.py` and `fixtures/eval/PROVENANCE.md` are purely additive (untracked new files).

---

## 8. Working tree

```
On branch main
Changes not staged for commit:
  modified: .gitignore
  modified: Makefile
  modified: README.md
  (+ spine files modified prior to this stage: NOTES.md, PM_LOG.md, STATE.md)

Untracked files:
  briefs/stage-8.md     (provided input brief)
  fixtures/eval/PROVENANCE.md
  pyproject.toml
  samples/              (3 files: .md, .csv, .jsonl)
  tests/test_stage8.py
  handbacks/stage-8.md  (this file)
```

No stray files. All untracked files are Stage 8 deliverables or inputs.

---

## 9. Next recommended action

PM re-runs `make test` (373+) + `make eval` (green) independently, then runs **`/security-review`** on the repo (the mandatory governance gate for Stage 8 per `PLAN.md`) to produce the anti-leakage / secret-handling findings report. Once `/security-review` findings are folded or surfaced as `DECISION-NEEDED`, Asaf signs off and the PM updates `STATE.md`, records metrics in `FACTS.md`, and commits (`git add` + `git commit`) to close Stage 8. Stage 9 (Brief/Deck + Technical Appendix) is then unblocked.
