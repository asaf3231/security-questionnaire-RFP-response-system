# Brief — Stage 3: Context Stack + draft generation + grounding

Read first (in order): `CLAUDE.md` → `PLAN.md` (Stage 3) → `QA_checklist.md` (`CTX1`–`CTX4`, `SCHEMA1`,
`DRAFT1`–`DRAFT2`, `GROUND1`) → `NOTES.md` (D-S3 + "Structural insights"), then this brief.

Goal: Assemble the 4-layer context "backpack", draft answers from it via a swappable `LLMProvider`
(offline `MockLLM` is the graded path; `ClaudeLLM` is the lazy network-gated live lane), and enforce
the byte-exact grounding gate. Fully offline + deterministic for the graded suite.

## Scope — do ONLY this stage

### 1. `app/context_stack.py` — `assemble_context()` (graded contract)
```python
def assemble_context(
    item: QuestionnaireItem,
    chunks: list[RetrievedChunk],
    *,
    item_number: int,
    total_items: int,
) -> ContextStack:
```
Build the 4 layers of the existing `ContextStack` schema (`instruction`, `retrieval: list[str]`,
`constraint`, `state`):
- **instruction** — explicit RFP/questionnaire handling rules + persona, from a **named module-level
  template constant** in this module (e.g. `INSTRUCTION_CONTEXT`). Not inline prose buried in the
  function; not in config.py (config is for cross-cutting magic values; the prompt template is this
  module's responsibility — mirrors the Reference's persona module).
- **retrieval** — `[f"[{c.chunk_id}] {text}" for c in chunks]` where `text` is the chunk's content
  (question+answer or answer). **ONLY the passed-in retrieved chunks** — nothing else (`CTX1`). The
  `[chunk_id]` marker lets `draft_answer` cite by id (D-S3).
- **constraint** — the active hard boundaries as text: a base rule ("answer ONLY from the retrieval
  context above; if it does not support an answer, say so — do not invent") PLUS, when
  `item.topic_tags ∩ HIGH_RISK_TAGS` (from config), a high-risk clause ("this item is high-risk
  (legal/security); do not assert a position without an approved doc — defer to human review"). Use
  **named template constants** for these.
- **state** — `f"Question {item_number} of {total_items}"` + the item's current pipeline state.

### 2. `app/llm.py` — the `LLMProvider` interface + two implementations (graded contract)
- `class LLMProvider(ABC)` with `@abstractmethod def draft(self, context_stack: ContextStack) -> DraftAnswer`.
- `class MockLLM(LLMProvider)` — **fully offline, deterministic** (seed with `RANDOM_SEED` if any
  ordering choice; prefer no randomness at all). Produces a `DraftAnswer` from the ContextStack: a
  templated `text` synthesized from the Retrieval-layer entries, and `citations=[Citation(chunk_id=…)]`
  for the chunk_ids it drew from (parse the `[chunk_id]` markers). Same ContextStack ⇒ identical
  DraftAnswer. Grounded by construction (text drawn from the cited chunks). Never networks.
- `class ClaudeLLM(LLMProvider)` — **lazy + network-gated.** Uses `config._get_claude()` (never builds
  the client at import). `draft()` builds the prompt from the 4 layers, calls the API with
  `DRAFT_MODEL`, `MAX_OUTPUT_TOKENS`, `DRAFT_TEMPERATURE` (0.0), instructs the model to return text +
  the cited `[chunk_id]`s (parse into `citations`). **Requirement #5:** wrap the call so ANY
  error/timeout/parse-failure returns `DraftAnswer(text=UNGROUNDED_PLACEHOLDER, citations=[])` (a clean
  routed-for-review degrade) — **never an unhandled exception, never a partial/invented answer.** Import-safe.

### 3. `app/draft.py` — `draft_answer()` + the grounding gate (graded contract, `RULE_GROUNDED_ONLY`)
- Add to `config.py` (§9) — **NEW named constants** (additions; the PM is surfacing these to Asaf):
  - `GROUNDING_COVERAGE_MIN = 0.5` (content-support threshold)
  - `GROUNDING_FAIL = "GROUNDING_FAIL"` (the §5.1 audit reason-code, materialized as a named constant;
    you MAY also materialize the other §5.1 reason-codes for consistency, but Stage 3 only needs this one).
- `grounding_check(draft: DraftAnswer, context_stack: ContextStack) -> GroundingResult` where
  `GroundingResult` is a small dataclass `(grounded: bool, answer: DraftAnswer, reason_code: str | None)`.
  A draft is **ungrounded** if ANY holds:
  1. `len(draft.citations) < GROUNDING_MIN_CITATIONS`, OR
  2. any `citation.chunk_id` is NOT among the chunk_ids present in the Retrieval layer (fabricated /
     unretrieved citation), OR
  3. **content coverage** < `GROUNDING_COVERAGE_MIN` — the fraction of the draft's significant content
     tokens (lowercase alphanumeric, minus a small fixed stopword set defined as a named constant) that
     appear in the union of the **cited** chunks' text.
  Ungrounded ⇒ `GroundingResult(grounded=False, answer=DraftAnswer(text=UNGROUNDED_PLACEHOLDER,
  citations=[]), reason_code=GROUNDING_FAIL)`. `UNGROUNDED_PLACEHOLDER` must be the **byte-exact**
  config literal (assert it byte-for-byte in the test). Grounded ⇒ `(True, draft, None)`.
- `draft_answer(context_stack: ContextStack, *, provider: LLMProvider | None = None) -> DraftAnswer`:
  `provider = provider or MockLLM()`; `raw = provider.draft(context_stack)`; return
  `grounding_check(raw, context_stack).answer`. (The reason-code is consumed by the pipeline/audit in
  Stages 5–6; expose `grounding_check` for direct testing.)

### 4. Tests (`CTX1`–`CTX4`, `SCHEMA1`, `DRAFT1`–`DRAFT2`, `GROUND1`) + progressive ENV4
- `CTX1` — all 4 layers present; Retrieval layer = ONLY the passed chunks (e.g. assemble with 2 chunks
  → exactly 2 retrieval entries, each containing its chunk_id + text; assert no other KB chunk text leaks in).
- `CTX2`/`CTX3`/`CTX4` — instruction layer carries the RFP rules; constraint layer injects the high-risk
  clause for a high-risk item (and not for a benign item); state layer = "Question X of Y".
- `SCHEMA1` — `DraftAnswer`/`Citation` validate; a malformed draft (empty text) rejected.
- `DRAFT1` — `draft_answer` over a MockLLM produces text + citations of retrieved chunk_ids;
  deterministic (two calls identical); offline (no network).
- `DRAFT2` *(offline degradation + live-gated)* — a provider whose `draft()` raises ⇒ `draft_answer`
  (or a degrade wrapper) yields `UNGROUNDED_PLACEHOLDER`, no exception. Mark the real-`ClaudeLLM` path
  `@pytest.mark.skipif(no ANTHROPIC_API_KEY)`.
- `GROUND1` — feed an ungrounded draft (no citations / a fake chunk_id / text with low coverage) ⇒
  `grounding_check` returns `reason_code == GROUNDING_FAIL` and `answer.text == UNGROUNDED_PLACEHOLDER`
  (byte-exact, imported from config). A grounded MockLLM draft passes unchanged.
- Add `app.context_stack`, `app.llm`, `app.draft` to the ENV4-progressive test (addition, not weakening).

## QA checks to PASS (run, not inspect): `CTX1`–`CTX4`, `SCHEMA1`, `DRAFT1`, `GROUND1` (+ `make test` green; `ENV4` clean). `DRAFT2` offline-degradation must pass; its live half is skip-gated.

## Constraints (from CLAUDE.md)
- Import-safe (`ENV4`): no client/network/.env/data read at import; `ClaudeLLM` uses the lazy
  `_get_claude()`; `MockLLM` is the default everywhere offline.
- Deterministic offline suite (§8): MockLLM identical output for identical input.
- Byte-exact `UNGROUNDED_PLACEHOLDER` (the graded literal) — from config, asserted byte-for-byte.
- No `data/*` value hardcoded in code/prompts (`KB2`/`LEAK3`).
- The 4-layer backpack is the ONLY context the model sees (`CTX1`) — nothing outside the retrieved chunks.

## Do NOT
- Touch any spine file (`CLAUDE.md`/`PLAN.md`/`QA_checklist.md`/`FACTS.md`/`STATE.md`/`NOTES.md`/
  `PM_LOG.md`) — PM-owned. (Adding the two NEW constants to `app/config.py` IS in scope — that's code,
  not a spine doc — but do not alter any EXISTING §9 constant value, literal, or `RULE_*`.)
- Change the `assemble_context` / `LLMProvider.draft` / `draft_answer` / `grounding_check` signatures
  above, or any existing schema field — surface as DECISION-NEEDED.
- Implement confidence, routing, state machine, audit, export, or the pipeline — Stages 4–6.
- Modify an existing graded test to make it pass (verifier-independence). Adding new tests / modules to
  the ENV4 list is fine. Do not commit.

## Deliver
Write `handbacks/stage-3.md` (CLAUDE §12.1 format). Report: the `make test` pass/skip count, files
created/modified (call out the two NEW config constants explicitly — `GROUNDING_COVERAGE_MIN`,
`GROUNDING_FAIL`), each `CTX*`/`SCHEMA1`/`DRAFT1`/`DRAFT2`/`GROUND1` ✅/⚠️ (test-verified), confirmation
`UNGROUNDED_PLACEHOLDER` is asserted byte-exact, any DECISION-NEEDED, and one next action. Return it as
your final message. The PM re-runs the checks, verifies the grounding gate + degradation independently,
runs `/code-review`, and records results in `FACTS.md`.
