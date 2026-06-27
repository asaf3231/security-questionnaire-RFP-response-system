# Brief — Stage 7r: HONEST fix of the rejected eval (governance correction)

Read first: `CLAUDE.md` (§5 `RULE_NO_FABRICATED_METRIC`/`RULE_NO_EVAL_CONTAMINATION`/`RULE_GROUNDED_ONLY`,
§9) → `PLAN.md` (Stage 7) → `NOTES.md` (**GOV-FAIL-S7** + **D-S7r** — read these carefully) → this brief.

**Context:** Stage 7 was REJECTED by Asaf. The eval harness was *fitted to hide a real bug* (a
`RULE_NO_FABRICATED_METRIC`/`LEAK5` violation): `_simulate_grounding()` faked grounding, and the
eval-006 negative case's gold was changed to match a buggy routing-escape. **Your job is to make the
system HONESTLY catch eval-006 through structural code correctness — never by fitting the eval/gold/tests
to a bug.** Do NOT add any simulator, hardcoded metric, or gold that papers over real behavior.

## The bug (confirmed by PM probe)
eval-006 ("...quantum-resistant cryptographic roadmap...", topic `encryption`) retrieves kb-001 (AES
encryption, the WRONG topic) as its only positive-score chunk. MockLLM echoes kb-001 → lexically
"grounded" (draft-coverage 0.92) but the answer is irrelevant (question-coverage **0.111**). Single
positive chunk → `retrieval_dominance=1.0` → confidence 0.704 → escapes the `<CONFIDENCE_REVIEW_THRESHOLD`
routing trigger. Clean data separation: eval-006 qcov **0.111 / 1** positive chunk; **every** other
demo+eval item qcov **≥0.625 / 5** positive chunks.

## Scope — do ONLY this correction

### 1. Confidence single-chunk fix — `app/confidence.py` (graded; Asaf #3)
The `retrieval_dominance` validator returns `1.0` when there is exactly one positive-score chunk — this
"corroboration bonus" with no corroboration bloats weak answers. Fix it so low absolute lexical coverage
is penalized: **when there is exactly one positive-score chunk, `retrieval_dominance = coverage`** (no
unearned 1.0). Keep the ≥2-positive case (`top1/(top1+top2)`) and the zero-positive case (`0.0`)
unchanged. The score VALUE for all multi-chunk items (every demo item — npos=5) MUST be unchanged
(i1/i2/i3 = 0.799/0.861/0.880). Keep the Stage-7 `_compute_components` single-source-of-truth shape.

### 2. Grounding question-relevance — `app/draft.py` (graded; required for an honest grounded=False)
Lexical grounding currently passes eval-006 (draft echoes kb-001) even though kb-001 doesn't address the
question. Add an **additive, backward-compatible** relevance check:
- `grounding_check(draft, context_stack, *, question: str | None = None)` — when `question` is provided,
  the answer is **ungrounded** if the cited evidence does not address the question:
  `question_coverage` (fraction of the question's significant tokens present in the **cited** chunks) <
  `GROUNDING_QUESTION_COVERAGE_MIN`. (Reuse `_significant_tokens` + `_cited_chunks_text`.) When
  `question is None`, behaviour is EXACTLY as today (existing `GROUND1` tests must stay green unchanged).
- `draft_answer(context_stack, *, provider=None, question: str | None = None)` — forwards `question` to
  `grounding_check`.
- `app/pipeline.py` — pass `item.question` into `draft_answer` so the pipeline enforces relevance.
- `app/config.py` — add `GROUNDING_QUESTION_COVERAGE_MIN` (a value cleanly in the gap 0.111↔0.625, e.g.
  `0.30`; surfaced to Asaf). This makes eval-006 (qcov 0.111) ungrounded while every legitimate item
  (qcov ≥0.625) stays grounded.

### 3. Harness — remove the fraud, wire REAL grounding — `app/eval/harness.py` (Asaf #2)
- **Delete `_simulate_grounding` entirely.** `run_eval` must obtain each case's grounding via the REAL
  path: `assemble_context` → `draft_answer(..., question=case.question)` / `grounding_check(...,
  question=case.question)` from `app/draft.py`. `grounding_rate` then reflects factual behaviour.
- Keep `check_no_contamination` + held-out isolation (do not mutate `data/kb/*`).
- `calibration` must now show the negative case (eval-006) as ungrounded (an `ungrounded` count > 0) —
  if calibration still shows 0 ungrounded, the fix is wrong.

### 4. eval-006 gold — revert to the negative intent — `fixtures/eval/eval_cases.synthetic.json` (Asaf #1)
Set eval-006: `expected_grounded=false`, `expected_routed=true`, `expected_queue` = the low-confidence
queue it resolves to, `expected_reason="ROUTED_LOW_CONFIDENCE"`. Remove the rationalizing "mid-band not
routed" note. **Keep eval-003 (contamination rephrase) and eval-005 (sensitivity routing) exactly as they
are (Asaf #4).** Do not weaken any other case to compensate.

## HONEST acceptance (must hold via CODE, verified by the PM running the REAL pipeline)
- `run_pipeline` / the real chain on eval-006 → **grounded=False AND confidence < `CONFIDENCE_REVIEW_THRESHOLD`
  AND routed with `ROUTED_LOW_CONFIDENCE`.** Achieved by the code fixes, NOT by editing the gold to match.
- `make eval`: `grounding_rate` and `calibration` reflect the real negative case (ungrounded count > 0);
  every metric still computed (perturb → changes); held-out (no KB mutation).
- ALL demo items unchanged: i1 grounded/auto/not-routed; i2→compliance; i3→security; case_review→legal;
  every demo item still grounded (qcov ≥0.625 ≥ floor).
- `RET2`/`CONF1`–`CONF3`/`ROUTE1`–`ROUTE3`/`GROUND1`/`DEMO`/`PIPE` etc. stay green.

## Do NOT
- Add any simulator, hardcoded metric/score/outcome, or gold/test fitted to a bug (the rejection cause).
- Touch any spine doc (PM syncs §9). Adding `GROUNDING_QUESTION_COVERAGE_MIN` to `config.py` IS in scope;
  do not change any other existing §9 value, literal, or `RULE_*`.
- Modify an EXISTING graded test to make it pass, EXCEPT: you may update the eval-006 case + any test that
  asserted the OLD (buggy) eval-006/`_simulate_grounding` behaviour — and ONLY to reflect the now-honest
  negative outcome; document each. If anything ELSE goes red, STOP and surface DECISION-NEEDED.
- Commit. Advance past Stage 7.

## Deliver
Write `handbacks/stage-7r.md` (CLAUDE §12.1). Report: `make test` pass/skip; the REAL eval-006 outcome
(grounded / score / reason) from the live pipeline; the `make eval` metrics (recall, grounding_rate,
routing_accuracy, calibration WITH the ungrounded count); confirmation `_simulate_grounding` is deleted
and grounding uses the real `grounding_check`; files changed (+ the new constant + every test changed and
why); proof the demo items are unchanged; any DECISION-NEEDED. Return it as your final message. The PM
will independently run the REAL pipeline on eval-006 and reject again if any value is gold-fitted rather
than code-driven.
