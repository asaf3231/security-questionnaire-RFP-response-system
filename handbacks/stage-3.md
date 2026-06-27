# Handback — Stage 3: Context Stack + Draft Generation + Grounding

**Date:** 2026-06-27
**Executer:** cold general-purpose agent
**Stage:** 3 — Context Stack + draft generation + grounding

---

## 1. What changed

**Files created:**
- `app/context_stack.py` — `assemble_context()` with the exact brief signature; 4-layer backpack;
  module-level template constants `INSTRUCTION_CONTEXT`, `_CONSTRAINT_BASE`, `_CONSTRAINT_HIGH_RISK_CLAUSE`.
- `app/llm.py` — `LLMProvider` ABC + `MockLLM` (offline, deterministic) + `ClaudeLLM` (lazy,
  network-gated, fully wraps all errors per DRAFT2).
- `app/draft.py` — `draft_answer()` + `grounding_check()` returning `GroundingResult` dataclass;
  `RULE_GROUNDED_ONLY` chokepoint; `_COVERAGE_STOPWORDS` named constant; `_ungrounded_result()` helper.
- `tests/test_stage3.py` — 46 tests covering CTX1–CTX4, SCHEMA1, DRAFT1, DRAFT2 (offline + live-gated),
  GROUND1, and progressive ENV4 (app.context_stack / app.llm / app.draft).

**Files modified:**
- `app/config.py` — added the two new Stage 3 named constants (additions only; no existing
  constant altered):
  - `GROUNDING_COVERAGE_MIN: float = 0.5` (D-S3 content-support threshold)
  - `GROUNDING_FAIL: str = "GROUNDING_FAIL"` (§5.1 audit reason-code, materialized as a constant)

---

## 2. DoD checklist

| QA ID | Status | Notes |
|---|---|---|
| `CTX1` | ✅ test-verified | 5 tests; retrieval layer = exactly the passed chunks; empty chunks → empty list |
| `CTX2` | ✅ test-verified | 4 tests; instruction = `INSTRUCTION_CONTEXT` constant; contains grounding + citation rules |
| `CTX3` | ✅ test-verified | 5 tests; high-risk clause injected for legal/security tags; absent for benign items |
| `CTX4` | ✅ test-verified | 3 tests; "Question X of Y" + item_id in state layer |
| `SCHEMA1` | ✅ test-verified | 6 tests; empty/whitespace text raises ValidationError; multiple citations work |
| `DRAFT1` | ✅ test-verified | 7 tests; MockLLM deterministic; citations from retrieval layer; offline; default provider |
| `DRAFT2` | ✅ offline-verified / 🔁 live-skipped | 3 offline tests (raising provider → UNGROUNDED_PLACEHOLDER, no exception); live test `@pytest.mark.skipif(no ANTHROPIC_API_KEY)` — skipped correctly |
| `GROUND1` | ✅ test-verified | 8 tests; all 3 ungrounded conditions (no citations / fabricated id / low coverage); UNGROUNDED_PLACEHOLDER byte-exact; GROUNDING_FAIL reason-code; grounded MockLLM draft passes unchanged |
| `ENV4` (progressive) | ✅ test-verified | subprocess + in-process import tests; `_claude_client` confirmed None after import |

---

## 3. QA results

**Run command:** `.venv/bin/pytest tests/ -v`

```
116 passed, 1 skipped in 0.73s
```

- Stage 1 tests: 39 passed (unchanged)
- Stage 2 tests: 32 passed (unchanged)
- Stage 3 tests: 45 passed, 1 skipped

**Skipped:** `TestDRAFT2::test_claude_llm_error_degrades_gracefully` — correctly `@pytest.mark.skipif`-gated on `ANTHROPIC_API_KEY` absent. This is the live-gated check per `QA_checklist.md` DRAFT2 spec; it is SKIPPED, not FAILED, in the offline suite.

**Zero regressions** across Stage 1 and Stage 2 tests.

**UNGROUNDED_PLACEHOLDER byte-exact assertion:** confirmed in
`TestGROUND1::test_ungrounded_placeholder_is_byte_exact` — the test imports the constant from
`app.config` and asserts both that `result.answer.text == UNGROUNDED_PLACEHOLDER` (imported) and
that `UNGROUNDED_PLACEHOLDER == "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"`.

**New constants verified:**
- `config.GROUNDING_COVERAGE_MIN == 0.5` — asserted in `test_both_new_config_constants_exist_and_correct`
- `config.GROUNDING_FAIL == "GROUNDING_FAIL"` — asserted in the same test

---

## 4. Decisions made

- **Grounding coverage stopword set** (`_COVERAGE_STOPWORDS`) — a named frozenset constant in
  `app/draft.py` (not inline, not in config.py). The brief requires "a small fixed stopword set
  defined as a named constant"; the set chosen is a standard English function-word list (≈50 words)
  that is orthogonal to the security/RFP domain. No external wordlist dependency.

- **`GroundingResult` is a Python `dataclass`** (not Pydantic) — it is an internal implementation
  detail of `draft.py`, not part of the schema contract. The Pydantic boundary is at `DraftAnswer`
  (the output). `GroundingResult` fields: `grounded: bool`, `answer: DraftAnswer`, `reason_code: str | None`.

- **`draft_answer()` wraps the provider call in try/except** — the brief (Requirement #5) explicitly
  requires `draft_answer` to be the catch-all for provider errors; `ClaudeLLM.draft()` also wraps
  internally (defence-in-depth). Both are needed: `ClaudeLLM` covers its own network errors;
  `draft_answer`'s outer try/except catches errors from any provider stub (including test stubs).

- **`MockLLM` derivation strategy** — assembles text by joining all retrieval entries in order
  (`"Based on [chunk_id]: <chunk_text>"`). This is deterministic by construction (no random state,
  no ordering nondeterminism because the retrieval list is already sorted), always grounded
  (draws exclusively from the cited retrieval chunks), and produces unique text per unique
  retrieval layer (satisfying the "draft uses only context stack" test).

- **`_format_retrieval_entry` in `context_stack.py`** — formats as `"[{c.chunk_id}] {text}"` where
  text = `c.question + " " + c.answer` if question exists, else `c.answer`. This mirrors the BM25
  document text construction in `retrieval.py`, ensuring the retrieval entry is the full semantic
  content the ranking saw.

- **State layer content** — `"Question {N} of {M} | Item ID: {item_id} | Current state: INTAKE"`.
  Uses `"INTAKE"` as the constant pipeline state at context-assembly time (Stages 4–5 will manage
  the actual state machine; this module does not depend on it). No stage-4 logic imported.

---

## 5. DECISION-NEEDED

None. No graded-contract change was made:
- All existing §9 constant values are unchanged.
- `LLMProvider.draft(context_stack) -> DraftAnswer` signature unchanged.
- `assemble_context()` signature unchanged.
- `grounding_check(draft, context_stack) -> GroundingResult` signature matches brief exactly.
- `draft_answer(context_stack, *, provider=None) -> DraftAnswer` signature matches brief exactly.
- `UNGROUNDED_PLACEHOLDER` and `REVIEW_BANNER` byte-exact literals unchanged.
- All existing `RULE_*` identifiers and their string values unchanged.
- No existing test modified.
- The two new constants (`GROUNDING_COVERAGE_MIN`, `GROUNDING_FAIL`) are additions flagged in D-S3
  and the brief; not changes to existing contracts.

---

## 6. Deviations / risks

- **None from PLAN.md.** All Stage 3 scope items implemented as specified.
- **No unpinned dependencies.** Stage 3 modules use only: `abc`, `re`, `dataclasses` (stdlib);
  `app.config`, `app.schema`, `app.llm` (internal). No new third-party packages.
- **ENV2 clean** — the `TestENV2` test passes across all 116 tests; no new third-party import
  is introduced that would require a new requirements.txt entry.
- **RULE_GROUNDED_ONLY chokepoint confirmed** — `app/draft.py` is the single module where
  `GROUNDING_FAIL` is emitted and `RULE_GROUNDED_ONLY` is referenced as its enforcement site,
  consistent with §5.1. The `RULE_GROUNDED_ONLY` constant is imported from config but not yet
  emitted to the audit log (that is Stages 5–6 scope; `grounding_check` exposes `reason_code`
  for the pipeline to consume).

---

## 7. Next recommended action

**PM:** run the QA checks independently (`.venv/bin/pytest tests/ -v`), re-verify
`UNGROUNDED_PLACEHOLDER` byte-exact in `grounding_check` output, then run `/code-review` on the
diff (this stage touches a graded contract: `LLMProvider` interface, `DraftAnswer`/`Citation`
schemas, `RULE_GROUNDED_ONLY` chokepoint, byte-exact literal). Record the suite count (116 pass,
1 skip) in `FACTS.md`, overwrite `STATE.md`, and mark Stage 3 ✅ in `PLAN.md` only after
independent verification.
