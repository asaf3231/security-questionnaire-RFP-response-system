# FACTS.md — Verified-Facts Ledger

Project: **Reindeer RFP / Security-Questionnaire Response Agent (codename "Comet")**
Maintained by: Asaf (PM)

> **The ONLY place a hard number/metric lives.** Every other file — `PLAN.md` status cells,
> `NOTES.md` / `PM_LOG.md` entries, `STATE.md`'s `Live-truth` snapshot, scripts, the Brief, the
> Appendix — **references a fact by name and never restates the literal value**. When a value changes,
> edit the one row here; the pointers don't move.
>
> A fact enters this ledger **only after it has been verified by running its source-of-truth command**
> — never copied from a draft or a handback. Re-verify before relying on any row (the methodology's
> "never report a number you haven't verified" rule). `STATE.md` numbers are a re-verify-me snapshot,
> not an authority — this file is the authority.
>
> **Config constants vs verified facts:** the named constants (`RETRIEVAL_TOP_K`,
> `CONFIDENCE_AUTO_THRESHOLD`, `RECALL_AT_K_TARGET`, the thresholds, the literals) live **once** in
> `CLAUDE.md` §9 / `app/config.py` and are referenced by name. This ledger holds **measured/empirical**
> numbers only (suite counts, computed metrics, demo outcomes, any live token spend).

| Fact | Value | Source-of-truth command | Verified | Commit |
|---|---|---|---|---|
| offline suite (`redteam/crazy-testing` branch, post-response-doc) | **596 pass / 1 skip / 2 xfail** (= 588 + **5** response-doc tests `tests/test_response_document.py` + **3** Sources-trailer tests `tests/test_sources_trailer.py`; all 588 prior **byte-identical**, 0 regressions). NB: branch ≠ main/Stage-8's 373 — the branch adds the red-team layer + Stage 10 + DN-QA50 + auto-tag + response-doc/Plan-A | `make test` | 2026-06-28 | (this commit) |
| cite-based sensitivity routing (Asaf-ratified graded signature add) | trigger 4 keys off **cited** chunks (`route_for_review(*, cited_chunk_ids=None)`; `pipeline.py` + `eval/harness.py` pass the draft's cited ids); aligns routing with the cite-based export gate. **Add-only, backward-compatible** (`None` ⇒ legacy all-chunks). Offline **byte-neutral**: `make test` 606 pass / 1 skip / 2 xfail; `make eval` routing_accuracy 1.0 (MockLLM cites all ⇒ DEMO1 i2 + eval-004/005 unchanged). Live `make demo-live` (q-demo-live-001): i1/i2/i6 now **confident auto-draft** (were ROUTED_SENSITIVE via retrieved-but-uncited kb-009); i7 still ROUTED_SENSITIVE→compliance (cites internal kb-010); i3/i4 ROUTED_HIGH_RISK→security | `make test` + `make eval` + `make demo-live` | 2026-06-29 | (this commit) |
| demo-live ungrounded-refusal (q-demo-live-001-i5) | i5 reworded → "What is your recertification renewal frequency in months?" (tokens absent from KB) ⇒ question_coverage ≤ 0.20 < `GROUNDING_QUESTION_COVERAGE_MIN` at **all** citation breadths (k1–k5) ⇒ deterministic `UNGROUNDED_PLACEHOLDER` → routed/held. Live: grounded=False, confidence 0.236 < `CONFIDENCE_REVIEW_THRESHOLD` → ROUTED_LOW_CONFIDENCE→gtm (single-run; live variance). Demo-input data only (not in graded suite) | `make demo-live` + offline `run_pipeline` qcov sweep | 2026-06-29 | (this commit) |
| auto-tagging at intake (`infer_tags`) | deterministic: untagged item ⇒ tags inferred from its retrieved chunks (score-weighted, filtered to `routing_map` keys ∪ `high_risk_tags`, top `AUTO_TAG_MAX`=3); threaded into routing (inferred legal/security ⇒ `ROUTED_HIGH_RISK`). Items WITH tags untouched ⇒ `make demo` **byte-unchanged**. Add-only (8 tests, incl. red cases) | `make test` + `make demo` | 2026-06-28 | bb1058d |
| live grounding — draft-prompt few-shot+structural (case_bulk20, 18 covered + 2 negatives) | grounded **10/20 → 14/20** after adding a mandatory inline-`[chunk_id]` rule + one-shot example to the draft TASK; false-ungrounded on covered items **8 → 4** (residual = model still drops markers, `cit=0`); negatives i19(bug-bounty)/i20(BC-DR) stay correctly ungrounded. **Live lane has run-to-run variance** (±1–2); single-run measurement | `python scripts/run_questionnaire.py --live` | 2026-06-28 | bb1058d |
| DN-QA50 PR-1/PR-2 (Asaf-ratified graded fix) | PR-1: ungrounded draft → 5th, lowest-precedence routing trigger `ROUTED_UNGROUNDED` (additive `route_for_review(*, grounded=True)`, eval-harness threaded); PR-2: `grounding_check` fails CLOSED on a contentless (zero-significant-token) question. **Add-only**; `make eval` **byte-identical** (no metric moved); `/code-review` clean (1 finding found+fixed: eval-harness real-path). Live audit `redteam/QA_AUDIT_50.md`; **PR-3/PR-4 DEFERRED** (sweep `redteam/SWEEP_PR3_PR4.md` ⇒ recommend `N=50`, band `[0.50,0.60)`; pending Asaf pin) | `make test` + `make eval` + `/code-review` | 2026-06-28 | 1f789cf |
| query refinement (Stage 10, `QREF*`/`DRAFT-COT*`) | MockLLM identity ⇒ offline retrieval byte-identical ⇒ `make eval` metrics UNCHANGED (recall 1.0 / raw_grounded 0.833 / routing 1.0 / review{u1}); `refine_query` audited per item (`original==optimized` offline); **defect fixed**: `item.question in ClaudeLLM._build_prompt` = True. **2026-06-28: draft `<thinking>` scaffold REMOVED** (live evidence: redteam/LIVE_RUN_FINDINGS .stage10 25/100 grounded WITH vs .nothinking 40/50 WITHOUT) — draft now requests inline `[chunk_id]` citations + answer-only; refine-query `<thinking>` + defensive draft-strip retained; `strip_thinking_block` is now a depth-aware nested-safe scan | `make test` + `make eval` + `make demo` | 2026-06-28 | 45c0dc6 |
| ~~offline suite (Stage 8)~~ | ~~373 pass / 1 skip~~ — **SUPERSEDED** by the branch suite row above (the `redteam/crazy-testing` branch adds the red-team layer + Stage 10) | `make test` | 2026-06-27 | stage-8-packaging |
| packaging + security gate (S8) | venv-clean Makefile (via `make test` no `source`); add-only (META-LOCK, tests/fixtures unmodified except the two-key COT retirement); pyproject boundary; redacted samples; **security scan CLEAN** (7 LEAK* + no-external-send) | `make test` + manual `/security-review`-equivalent scan | 2026-06-27 | stage-8-packaging |
| eval metrics (`EVAL1`/`EVAL3`, `make eval`) — HONEST | recall@k 1.0 · grounding match_rate 1.0 / **raw_grounded 0.833** (eval-006 ungrounded) · routing_accuracy 1.0 · calibration auto{g5,u0}/**review{g0,u1}** (negative case exposed) | `make eval` (PM-verified computed: perturb gold → routing_acc 1.0→0.833; real `grounding_check`, no simulator) | 2026-06-27 | stage-7-eval (honest, 7r) |
| eval-006 negative test (honest, code-driven) | grounded=False · score 0.074 < `CONFIDENCE_REVIEW_THRESHOLD` · ROUTED_LOW_CONFIDENCE | PM ran the REAL pipeline (not gold-fitted) | 2026-06-27 | stage-7-eval (honest, 7r) |
| Recall@K post-refactor (`RET2`) | Recall@5 = 1.0000 (held after full-corpus BM25 index, D-S6) | `python -c "from app.eval.fixtures import load_eval_fixtures as L;from app.eval.rubric import compute_recall_at_k as C;print(C(L()))"` | 2026-06-27 | stage-6-pipeline |
| demo behavior (`DEMO1`/`DEMO2`) | confident i1(pub,0.799)→approved→exported; i2(internal,0.861)→ROUTED_SENSITIVE→compliance (Option A); i3(restricted+security,0.880)→ROUTED_HIGH_RISK→security; case_review both→ROUTED_HIGH_RISK→legal (not exported) | `make demo` (venv) | 2026-06-28 | stage-6-pipeline (Option A since stage-7-eval) |
| import-safety (`ENV4`, Stage-5 scope) | clean; lazy `_claude_client` `None` (14 modules); **no `audit/`/`exports/` dir created at import** (PM-verified) | `python -c "import app.config, app.schema, app.kb, app.retrieval, app.eval.rubric, app.eval.fixtures, app.context_stack, app.llm, app.draft, app.confidence, app.routing, app.state, app.audit, app.export"` (empty cwd, no `.env`; progressive) | 2026-06-27 | stage-5-export |
| demo routing (real data, `ROUTE*`) | case_confident i1 → auto (score 0.799, not routed); i2 → ROUTED_SENSITIVE→compliance (internal sensitivity, Option A); i3 → ROUTED_HIGH_RISK→security (security tag); case_review both → ROUTED_HIGH_RISK→legal | `make demo` (mirrors `route_for_review` on `data/questionnaires/*`) | 2026-06-28 | stage-4-routing (i2 routing since Option A / stage-7-eval) |
| synthetic KB size | 20 chunks / 19 approved / 5 restricted-or-internal / 20 unique ids | `python -c "import app.kb as k;c=k.load_kb();print(len(c))"` | 2026-06-27 | stage-1-env |
| pinned deps | 24 pins (pydantic 2.13.4 · rank-bm25 0.2.2 · anthropic 0.112.0 · python-dotenv 1.2.2 · pytest 9.1.1); venv py 3.12.4 | `grep -c '==' requirements.txt` | 2026-06-27 | stage-1-env |
| Recall@K (`RET2`) | Recall@5 = 1.0000 (12/12 fixtures; ≥ `RECALL_AT_K_TARGET`); **computed** (perturb→0.0) | `python -c "from app.eval.fixtures import load_eval_fixtures as L; from app.eval.rubric import compute_recall_at_k as C; print(C(L()))"` | 2026-06-27 | stage-2-retrieval |
| live draft token spend (if run) | _optional; not run this pass — live behavior characterized qualitatively in `redteam/LIVE_RUN_FINDINGS*.md`_ | `make demo-live` | — | — |

> _Resolved-and-promoted: grounding rate / routing accuracy / calibration (`EVAL1`/`EVAL3`) now live in
> the "eval metrics" row; `DEMO1`/`DEMO2` outcomes in the "demo behavior" row — the earlier
> "_pending Stage 6/7_" placeholder rows were removed (the metrics shipped)._

**Acceptance bars referenced by name (defined once in `CLAUDE.md` §9, not restated as numbers here):**
`RETRIEVAL_TOP_K`, `BM25_K1`, `BM25_B`, `RECALL_AT_K_TARGET`, `CONFIDENCE_AUTO_THRESHOLD`,
`CONFIDENCE_REVIEW_THRESHOLD`, `GROUNDING_MIN_CITATIONS`, `AMBIGUITY_SCORE_MARGIN`,
`MAX_OUTPUT_TOKENS`, `DRAFT_TEMPERATURE`, `RANDOM_SEED`.

> Rows are filled in by the PM at each stage's verification (running the source-of-truth command),
> never by the executer and never copied from a handback.
