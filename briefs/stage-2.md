# Brief — Stage 2: KB chunks + deterministic retrieval (`rank_bm25`)

Read first (in order): `CLAUDE.md` → `PLAN.md` (Stage 2) → `QA_checklist.md` (`RET1`–`RET3`) →
`NOTES.md` ("Structural insights" + "Stage 2 follow-ups"), then this brief.

Goal: Implement deterministic lexical retrieval over the approved KB using the pinned `rank_bm25`
library, with strict topic/sensitivity filtering, and measure **Recall@K** on labeled fixtures —
fully offline, fully reproducible.

## Scope — do ONLY this stage

### 0. First, clear the two deferred Stage-1 `kb.py` findings
- Remove the dead sub-condition `and required_field != "approved"` in `_validate_kb_record`
  (the loop never includes `"approved"`).
- Add **strict `chunk_id` uniqueness validation** in `load_kb()`: collect ids across
  `approved_answers.synthetic.json` **and** all `docs/*.synthetic.json`; a duplicate `chunk_id` raises
  a clean explicit `ValueError` naming the offending id (latent: dup ids would break Stage-2
  citations/ranking). Add tests for both (a duplicate-id KB → `ValueError`).

### 1. `app/retrieval.py` — the graded `retrieve()` contract (do NOT deviate; surface as DECISION-NEEDED if wrong)
```python
def retrieve(
    question: str,
    *,
    topic_tags: list[str] | None = None,
    allowed_sensitivities: list[str] | None = None,
    top_k: int = RETRIEVAL_TOP_K,
) -> list[RetrievedChunk]:
```
Behavior:
- **Corpus = `load_kb()` chunks with `approved == True` only.** A non-approved chunk is **never**
  retrievable (hard rule). The atomic unit is the **full chunk** (paragraph / approved-answer) — no
  sub-paragraph splitting (Asaf principle B).
- **Rank with `rank_bm25`** (`BM25Okapi`, params `BM25_K1`/`BM25_B` from `config.py`). Tokenize
  deterministically: lowercase + split on a fixed non-alphanumeric regex; the document text per chunk
  is a stable concatenation (e.g. `question` + " " + `answer`); same for the query.
- **Topic filter (strict):** if `topic_tags` is non-empty, restrict the corpus to chunks sharing ≥1
  topic tag before ranking.
- **Sensitivity filter:** if `allowed_sensitivities` is provided, restrict the corpus to chunks whose
  `sensitivity ∈ allowed_sensitivities`. **Default `None` = all sensitivities pass** — retrieval sees
  all approved chunks (incl. `internal`/`restricted`) so the agent can draft grounded answers; the
  sensitivity **gate** is enforced downstream at routing/export (`RULE_SENSITIVITY_GATE`, Stages 4/5),
  NOT here. (This is the deliberate design — document it in the module docstring.)
- Return the top `top_k` as `RetrievedChunk` objects with `bm25_score` **set** to the computed score,
  sorted by score **descending with a deterministic tiebreak by `chunk_id`** (so `RET3` holds).
- No network; no `.env`; import-safe (no work at import).

### 2. `app/eval/` (recreate the package — Stage 2 legitimately needs it now)
- `app/eval/__init__.py` (empty), `app/eval/fixtures.py` (loader for `fixtures/eval/`),
  `app/eval/rubric.py` with a **computed** metric:
  ```python
  def compute_recall_at_k(fixtures, k: int = RETRIEVAL_TOP_K) -> float: ...
  ```
  Recall@K = fraction of labeled queries for which **≥1** labeled-relevant `chunk_id` appears in the
  top-`k` returned by `retrieve(query, topic_tags=...)`. **Computed from the fixtures every call —
  never hardcoded** (`RULE_NO_FABRICATED_METRIC`). Do not hardcode `0.90` or any score anywhere.

### 3. `fixtures/eval/` — labeled gold (synthetic, tracked, held-out-aware)
- Seed ~8–12 labeled records: `{ "query": "...", "relevant_chunk_ids": ["..."], "topic_tags": [...] }`
  whose `relevant_chunk_ids` exist in the KB. The labeled-relevant chunk **legitimately lives in the
  KB** — that is what retrieval must find (this is Recall@K, NOT the answer-eval contamination guard;
  see NOTES "Recall@K ≠ eval contamination"). Design queries BM25 can plausibly satisfy so the
  measured Recall@K meets `RECALL_AT_K_TARGET`. **If it does not, report the real number — do not tune
  the metric or the test to pass.**

### 4. Tests (`RET1`–`RET3`) + progressive ENV4
- `RET1` — `retrieve()` returns ≤ `RETRIEVAL_TOP_K` approved chunks; non-approved never returned;
  topic filter and `allowed_sensitivities` filter each work; uses `BM25_K1`/`BM25_B`; no network.
- `RET2` — `compute_recall_at_k` over `fixtures/eval/` returns a computed float meeting
  `RECALL_AT_K_TARGET`; assert it is computed (e.g. perturbing a fixture changes the result).
- `RET3` — determinism: two sequential `retrieve()` calls return **identical** ranked `chunk_id`
  lists; ties broken by `chunk_id`.
- Add `app.retrieval`, `app.eval.rubric`, `app.eval.fixtures` to the ENV4 `MODULES_TO_TEST` list
  (progressive ENV4 — this is an addition, not a weakening).

## QA checks to PASS (run, not inspect): `RET1`, `RET2`, `RET3` (+ `make test` stays green; `ENV4` still clean)

## Constraints (from CLAUDE.md)
- Use the established `rank_bm25` lib — do **not** hand-roll BM25 (Asaf principle B).
- Deterministic + offline + import-safe (§8); no magic values inline — `RETRIEVAL_TOP_K`/`BM25_*`/
  `RECALL_AT_K_TARGET` come from `config.py`.
- No `data/*`/fixture value hardcoded in `app/` (`KB2`/`LEAK3`).
- `RULE_NO_FABRICATED_METRIC`: every metric computed from labeled input.

## Do NOT
- Touch any spine file (`CLAUDE.md`/`PLAN.md`/`QA_checklist.md`/`FACTS.md`/`STATE.md`/`NOTES.md`/
  `PM_LOG.md`) — PM-owned. The PM records Recall@K in `FACTS.md` after re-verifying.
- Change the `retrieve()` signature above, a §9 constant, a schema field, or a `RULE_*` — surface as
  DECISION-NEEDED.
- Implement the context stack, drafting, confidence, routing, state, audit, export, or the full eval
  harness — Stages 3–7.
- Modify an existing graded test to make it pass (verifier-independence). Adding new tests / adding
  modules to the ENV4 list is fine. Do not commit.

## Deliver
Write `handbacks/stage-2.md` (CLAUDE §12.1 format). Report: the **measured Recall@K** (the exact
float), the `make test` pass/skip count, files created, each `RET*` ✅/⚠️ (test-verified), confirmation
the two deferred `kb.py` findings are fixed, any DECISION-NEEDED, and one next action. Return it as
your final message. The PM re-runs `RET1`–`RET3`, re-computes Recall@K independently, runs
`/code-review`, and records the number in `FACTS.md`.
