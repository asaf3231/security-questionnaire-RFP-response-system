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
| offline suite | _pending Stage 1_ | `make test` | — | — |
| import-safety (`ENV4`) | _pending Stage 1_ | `python -c "import app.config, app.schema, app.kb, app.retrieval, app.context_stack, app.llm, app.draft, app.confidence, app.routing, app.state, app.audit, app.export, app.pipeline"` | — | — |
| Recall@K (`RET2`) | _pending Stage 2_ | `make eval` | — | — |
| grounding rate (`EVAL1`) | _pending Stage 7_ | `make eval` | — | — |
| routing accuracy (`EVAL1`) | _pending Stage 7_ | `make eval` | — | — |
| confidence calibration (`EVAL3`) | _pending Stage 7_ | `make eval` | — | — |
| demo case 1 outcome (`DEMO1`) | _pending Stage 6_ | `make demo` | — | — |
| demo case 2 outcome (`DEMO2`) | _pending Stage 6_ | `make demo` | — | — |
| live draft token spend (if run) | _pending / optional_ | `make demo-live` | — | — |

**Acceptance bars referenced by name (defined once in `CLAUDE.md` §9, not restated as numbers here):**
`RETRIEVAL_TOP_K`, `BM25_K1`, `BM25_B`, `RECALL_AT_K_TARGET`, `CONFIDENCE_AUTO_THRESHOLD`,
`CONFIDENCE_REVIEW_THRESHOLD`, `GROUNDING_MIN_CITATIONS`, `AMBIGUITY_SCORE_MARGIN`,
`MAX_OUTPUT_TOKENS`, `DRAFT_TEMPERATURE`, `RANDOM_SEED`.

> Rows are filled in by the PM at each stage's verification (running the source-of-truth command),
> never by the executer and never copied from a handback.
