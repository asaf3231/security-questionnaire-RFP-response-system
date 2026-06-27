# Brief — Stage 8: Packaging Hardening & Production Readiness

Read first (in order): `CLAUDE.md` (esp. §1 env/reproduce, §2 layout, **§5 incl. the new
`RULE_GRADED_ARTIFACT_LOCK` / `RULE_METRIC_FALSIFIABLE`**, §8) → `PLAN.md` (Stage 8) →
`QA_checklist.md` (`LEAK1`–`LEAK-S`, `PKG1`–`PKG3`, `SEC1`–`SEC2`, **§15 `META-*`**) → `NOTES.md`
(GOV-HARDENING + D-S8), then this brief.

Goal: make the repo production-ready — venv-clean Makefile, anti-leakage hardening, a strict package
boundary with a clean working tree, redacted demo samples — then it goes to the `/security-review` gate.
Fully offline + deterministic.

## ⛔ BINDING governance (read before touching anything)
- **`RULE_GRADED_ARTIFACT_LOCK`:** `tests/` and `fixtures/` are **ADD-ONLY**. You may add new
  tests/fixtures; you may **NOT modify or delete** any existing tracked test/fixture. **NEVER set
  `ALLOW_GRADED_EDIT`** (that is a human-only key). `make test`/`make eval` run the `integrity`
  pre-flight which aborts on any modify/delete. If you think an existing test must change, STOP and
  surface DECISION-NEEDED.
- **`RULE_METRIC_FALSIFIABLE`:** no `_simulate_*` shortcuts; keep the real path + the red negative case.
- Do not change any §9 constant, schema field, byte-exact literal, or `RULE_*` — surface DECISION-NEEDED.

## Scope — do ONLY this stage

### 1. venv-clean Makefile + path alignment (req #1)
- Make `test` / `demo` / `demo-live` / `eval` run cleanly **without a manually-activated venv**: define
  `PY := .venv/bin/python` and `PYTEST := .venv/bin/pytest`, and a guard so that if `.venv/bin/python`
  is missing the target prints a clear bootstrap message (`python3 -m venv .venv && make install`) and
  exits non-zero — **never silently fall back to system python** (that is what broke `rank_bm25`).
- **KEEP** Asaf's `integrity` pre-flight exactly as-is; `test` and `eval` still depend on it. Do not
  weaken or remove it.
- Eval path: `make eval` already runs `python -m app.eval.harness` (the spine path `app/eval/harness.py`
  — RESOLVED). Just switch it to `$(PY) -m app.eval.harness`. No rename, no new eval module.

### 2. Anti-leakage & hardening (req #2; `LEAK1`–`LEAK-S`, `SEC1`–`SEC2`)
- **`.gitignore` completeness:** `.env`, `.venv/`, `exports/`, `audit/`, `__pycache__/`, `*.pyc`,
  `.pytest_cache/`, `.DS_Store` (+ any real/customer data). Verify with `git check-ignore`.
- **No dev/debug artifacts in `app/`:** grep `app/` for `print(` (outside the structured logger),
  `breakpoint(`, `import pdb`, `TODO`, `FIXME`, dead/commented-out code — remove any found in `app/`.
  (Demo `scripts/` may legitimately print.)
- **Eval fixtures are dev-only:** `fixtures/` + `tests/` are excluded from the package boundary (§3).
- **Re-prove all 7 leakage protections** over the full tracked set (`LEAK1` secret, `LEAK2` PII, `LEAK3`
  hardcoded-input, `LEAK4` eval-contamination, `LEAK5` fabricated-metric, `LEAK-G` grounding, `LEAK-S`
  sensitivity) — as runnable checks (add to a new `tests/test_stage8.py`).

### 3. Final packaging — strict boundary, clean tree (req #3; `PKG1`–`PKG3`)
- Add a minimal **`pyproject.toml`**: project metadata, `requires-python = ">=3.11"`, package =
  `app` (and `app.eval`); **exclude `tests/`, `fixtures/`, `data/` dev artifacts from any dist**.
  (Additive — does not change runtime behavior.)
- **README** "Package boundary + run-from-clean-checkout" section: the one-command path (now venv-clean),
  what ships (`app/` + `data/*.synthetic.*` runtime inputs) vs dev-only (`tests/`, `fixtures/`, `scripts/`),
  and the `make demo` / `make demo-live` / `make eval` distinction.
- **Track ONE redacted sample of each output** (CLAUDE §2): run `make demo`, then copy a **redacted**
  sample response doc (`.md` + `.csv`) and a **redacted** audit (`.jsonl`) into a **tracked** location
  (e.g. `samples/` — a new dir, or a `.gitignore` exception under `exports/`/`audit/`). Redact any
  machine-local paths/timestamps to stable placeholders. These show reviewers the output shape; the live
  `exports/`/`audit/` stay gitignored.
- **`META-PROVENANCE` (lock-safe):** add a NEW file `fixtures/eval/PROVENANCE.md` deriving each eval/gold
  case from the spec/intent (this is an ADD — do NOT edit the locked `eval_cases.synthetic.json`).
- Leave the working tree clean (no stray files).

### 4. Pre-flight (req #4) + new tests
- `tests/test_stage8.py` (NEW — add-only): assert `PKG1` (clean-checkout reproduction shape), `PKG2`
  (`.gitignore` correctness via `git check-ignore`), `PKG3` (README + module docstrings present), the 7
  `LEAK*` greps, and `META-FALSIFY`/`META-REALPATH` sanity (eval has a red negative case; no `_simulate_*`
  in `app/`). Use only stdlib + the repo.
- Add `app.eval.harness` etc. as needed to the ENV4-progressive import set if any module is new (none expected).

## QA checks to PASS (run, not inspect): `LEAK1`–`LEAK-S`, `PKG1`–`PKG3`, `SEC1`–`SEC2`, `META-LOCK`/`META-FALSIFY`/`META-REALPATH`/`META-PROVENANCE`; `make test` (315+) green via the venv-clean Makefile; `make eval` green; working tree clean.

## Do NOT
- Modify/delete any existing test or fixture (RULE_GRADED_ARTIFACT_LOCK — add-only); never set
  `ALLOW_GRADED_EDIT`. Remove/weaken Asaf's `integrity` pre-flight. Change a §9 constant/schema/literal/
  `RULE_*`. Reintroduce any `_simulate_*` shortcut. Commit. Advance past Stage 8.

## Deliver
Write `handbacks/stage-8.md` (CLAUDE §12.1). Report: `make test` + `make eval` results **run through the
new venv-clean Makefile** (paste the commands + counts); files created/modified (call out the Makefile
venv change, `pyproject.toml`, `.gitignore`, the redacted samples, `PROVENANCE.md`, `tests/test_stage8.py`);
each `LEAK*`/`PKG*`/`SEC*`/`META-*` ✅/⚠️; confirmation NO existing test/fixture was modified (add-only) and
`ALLOW_GRADED_EDIT` was never set; working tree clean; any DECISION-NEEDED; one next action. Return it as
your final message. The PM re-runs everything, runs **`/security-review`** on the repo, and records in `FACTS.md`.
