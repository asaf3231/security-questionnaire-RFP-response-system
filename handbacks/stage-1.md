# Handback — Stage 1: Environment, secrets, config & synthetic inputs

**Executer:** cold general-purpose subagent
**Date:** 2026-06-27
**Stage:** 1 of 9

---

## 1. What changed

### Files created (all new):

**Environment / packaging:**
- `requirements.txt` — all 5 required packages + transitives, pinned with `==`
- `.env.example` — placeholder only (`ANTHROPIC_API_KEY=your-api-key-here`)
- `.gitignore` — covers `.env`, `.venv/`, `exports/`, `audit/`, `__pycache__/`, `*.pyc`, `.DS_Store`, real data
- `Makefile` — `install` and `test` targets only (no dead/TODO targets; demo/eval arrive in later stages)
- `README.md` — clean-checkout path per CLAUDE.md §1; synthetic-data disclaimer; later-stage targets noted
- `conftest.py` — root conftest adding repo root to sys.path for pytest

**App modules:**
- `app/__init__.py` — empty package marker
- `app/config.py` — full §9 implementation: all constants, byte-exact literals, 11 RULE_* strings, AGENT_TOOLS with import-time uniqueness assert, lazy `_get_claude()` singleton (never called at import), `load_env()` helper (never called at import)
- `app/schema.py` — full Pydantic models: QuestionnaireItem, RetrievedChunk, ContextStack, Citation, DraftAnswer, ConfidenceResult, RoutingDecision, AuditEvent, ResponseDoc, ResponseDocItem; validators raise on malformed input
- `app/kb.py` — load+validate only (no ranking): `load_kb()`, `load_questionnaire(path)`, `load_policy_tags()`; strict `ValueError` on any missing/invalid field; sensitivity validated against SENSITIVITY_TAGS; routing map validated against REVIEWER_QUEUES

**Final `app/` contents (4 files — see reviewer-gate correction below):**
- `app/__init__.py`, `app/config.py`, `app/schema.py`, `app/kb.py`

> **Reviewer-gate correction applied (one round):** the initial draft pre-stubbed 10 docstring-only
> Stage 2–7 modules (`retrieval.py`, `context_stack.py`, `llm.py`, `draft.py`, `confidence.py`,
> `routing.py`, `state.py`, `audit.py`, `export.py`, `pipeline.py`) plus the `app/eval/` package
> (`__init__.py`, `harness.py`, `rubric.py`, `fixtures.py`). These were **deleted** per CLAUDE.md §8
> ("no dead/scratch code… no TODO-only modules — what ships is what runs"). Modules are now created
> by the stage that implements them. ENV4 is proven **progressively per stage** (CLAUDE.md §1): the
> Stage 1 ENV4 test imports only the modules that exist now (`app.config`, `app.schema`, `app.kb`);
> the full 13-module import is re-proven as later stages land their modules.

**Synthetic data (all `*.synthetic.*`, all fake):**
- `data/kb/approved_answers.synthetic.json` — 16 records: 13 approved, 1 not-approved (kb-014), mixes of public/internal/restricted, varied topic_tags; includes legal/security (high-risk) restricted records for case_review
- `data/kb/docs/product_security_overview.synthetic.json` — 4 doc paragraph chunks
- `data/questionnaires/case_confident.synthetic.json` — 3 items with strong public KB coverage, no high-risk tags (DEMO1)
- `data/questionnaires/case_review.synthetic.json` — 2 items with legal+security high-risk tags and restricted KB entries (DEMO2)
- `data/policy_tags.synthetic.json` — defines sensitivity_tags, high_risk_tags, routing_map (all queues ⊆ REVIEWER_QUEUES)

**Tests:**
- `tests/__init__.py` — empty
- `tests/test_stage1.py` — 39 tests covering ENV2, ENV4, config constants, KB1, DATA1, KB2, SEC1

**Git hygiene:**
- `git rm --cached .DS_Store` — executed (was tracked; now removed from index and will be gitignored)

**Directories created (gitignored/placeholder):**
- `exports/`, `audit/`, `fixtures/eval/`, `scripts/`, `handbacks/`, `brief/`, `appendix/`

---

## 2. DoD checklist

| QA ID | Status | Notes |
|-------|--------|-------|
| `ENV1` | ✅ test-verified | venv created with python3.12; `pip install -r requirements.txt` exits 0; all 5 required + 19 transitive packages resolve |
| `ENV2` | ✅ test-verified | `TestENV2::test_all_third_party_imports_pinned` passes; dotenv→python-dotenv alias handled |
| `ENV3` | ✅ test-verified | `pytest -q` (= `make test`) runs clean with no `.env`, no network; 39 passed |
| `ENV4` | ✅ test-verified | `TestENV4` (3 tests, **scoped to `app.config`/`app.schema`/`app.kb`** — the only modules existing at Stage 1) + manual subprocess re-proof from `/tmp`; all import clean; `_claude_client is None` confirmed; deleted Stage 2+ modules confirmed gone (ModuleNotFoundError each) |
| `SEC1` | ✅ test-verified | `TestSEC1` (3 tests); git-tracked set clean; `.env` gitignored; `.env.example` placeholder only |
| `SEC2` | ✅ test-verified | No `exports/` or `audit/` artifacts are tracked; grep clean |
| `KB1` | ✅ test-verified | `TestKB1` (9 tests); valid KB loads; missing chunk_id/answer/sensitivity → ValueError; invalid sensitivity → ValueError; approved==False chunk present |
| `DATA1` | ✅ test-verified | `TestDATA1` (9 tests); both questionnaires load; policy_tags load; routing map validated against REVIEWER_QUEUES; malformed inputs → ValueError |
| `KB2` | ✅ test-verified | `TestKB2::test_no_kb_answer_literals_in_app_code` passes; no data/* literal in app/ code |

---

## 3. QA results

After the reviewer-gate correction (stub removal + ENV4 scoping + SEC1 precision fix):

```
make test  →  pytest -q
.......................................
39 passed in 0.30s
```

(Test count unchanged at 39: ENV4 now imports 3 modules instead of 13 within the same 3 ENV4
test functions; no tests added or removed by the correction.)

Manual ENV4 re-proof (from /tmp, no .env, no ANTHROPIC_API_KEY):
```
ENV4 PASS (Stage 1 scope): app.config, app.schema, app.kb imported; no side effects; _claude_client is None
Confirmed: all premature Stage 2+ stub modules are removed (ModuleNotFoundError on each)
```

SEC1 scan: CLEAN (no real `sk-ant-...` key, no real key value in any tracked file).

---

## 4. Decisions made

**D-S1-1 (Python version):** Python 3.12.4 used (at `/opt/miniconda3/envs/BB84/bin/python3.12`). The system `python3` is 3.10.17 (below the §1 requirement of 3.11+), so `python3.12` was used for venv creation. README says "Python 3.11 or higher." This is consistent with CLAUDE.md §1 — no graded contract change.

**D-S1-2 (Stub modules — REVERSED by reviewer-gate correction):** The initial draft pre-stubbed the
Stage 2–7 modules. Per the reviewer gate (CLAUDE.md §8), these were deleted; modules are created by
the stage that implements them and ENV4 is proven progressively. The final `app/` tree contains only
`__init__.py`, `config.py`, `schema.py`, `kb.py`.

**D-S1-3 (KB doc chunks bm25_score default):** `RetrievedChunk.bm25_score` is set to `0.0` at load time. Stage 2 will populate this from rank_bm25. This is not a graded contract.

**D-S1-4 (.DS_Store removal):** `git rm --cached .DS_Store` was run as instructed by the brief. The file is now ignored.

**D-S1-5 (SEC1 test precision):** During the correction round, the SEC1 tracked-file scan was made
precise — it now matches a real key shape via regex `sk-ant-[A-Za-z0-9_\-]{20,}` (contiguous, no
whitespace) instead of a loose "`sk-ant-` + 20 chars after it" heuristic that false-positived on prose
mentioning the prefix. This is a strictly stronger/cleaner SEC1 check, not a weakening — it still flags
any real key or any `ANTHROPIC_API_KEY=<value>` assignment outside `.env.example`. Removed the unused
`importlib` import; added `re`.

---

## 5. DECISION-NEEDED

None. No graded contracts were changed. All §9 constants, RULE_* strings, byte-exact literals, schema field names, and tool signatures are as specified in CLAUDE.md §9.

---

## 6. Deviations / risks

**None material.** Notes:

- The SEC1 scan is now regex-precise (see D-S1-5), so prose mentioning `sk-ant-` (including this
  handback and the test source) no longer false-positives, while a real key still trips the check.

**Known follow-ups DEFERRED to Stage 2 (per coordinator — do NOT fix in Stage 1):**

1. **Dead sub-condition in `_validate_kb_record` (`app/kb.py`):** the `and required_field != "approved"`
   clause in the empty-value guard is dead — `"approved"` is not in the required-fields tuple
   (`chunk_id`, `answer`, `sensitivity`), so the condition is always True. Harmless; remove in Stage 2.
2. **`chunk_id` uniqueness:** `load_kb()` does not yet assert `chunk_id` uniqueness across
   `approved_answers` + `docs/`. Add a uniqueness check in Stage 2 when retrieval indexes by `chunk_id`.

---

## 7. Next recommended action

**Stage 2: KB chunks + deterministic retrieval (`rank_bm25`)**

The PM should re-run `make test` independently (39 tests expected), then run the `/code-review` gate (constants, schema, RULE_* strings are graded contracts), and if clean, spawn a cold executer for Stage 2 (`RET1`–`RET3`: **create** `app/kb.py` ranking half + `app/retrieval.py` using `rank_bm25` + tag filter; fold in the two deferred follow-ups above; build the labeled `fixtures/eval/` seed; prove Recall@K; extend the ENV4 import list to include the new module).

---

## Pinned dependency versions (for PM to record in FACTS.md)

| Package | Version |
|---------|---------|
| pydantic | 2.13.4 |
| pydantic_core | 2.46.4 |
| rank-bm25 | 0.2.2 |
| anthropic | 0.112.0 |
| python-dotenv | 1.2.2 |
| pytest | 9.1.1 |
| annotated-types | 0.7.0 |
| anyio | 4.14.1 |
| certifi | 2026.6.17 |
| distro | 1.9.0 |
| docstring_parser | 0.18.0 |
| h11 | 0.16.0 |
| httpcore | 1.0.9 |
| httpx | 0.28.1 |
| idna | 3.18 |
| iniconfig | 2.3.0 |
| jiter | 0.15.0 |
| numpy | 2.5.0 |
| packaging | 26.2 |
| pluggy | 1.6.0 |
| Pygments | 2.20.0 |
| sniffio | 1.3.1 |
| typing-inspection | 0.4.2 |
| typing_extensions | 4.15.0 |

Python runtime: 3.12.4 (venv at `.venv/`)
