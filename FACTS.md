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
| offline suite (`redteam/crazy-testing` branch, post-DN-QA50) | **580 pass / 1 skip / 2 xfail** (= 569 Stage-10 baseline + **11** DN-QA50 PR-1/PR-2 tests in `tests/test_dn_qa50_pr1_pr2.py`; the existing 569 are **byte-identical**, 0 regressions). NB: branch ≠ main/Stage-8's 373 — the branch adds the red-team layer + Stage 10 + DN-QA50 | `make test` | 2026-06-28 | 1f789cf |
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
