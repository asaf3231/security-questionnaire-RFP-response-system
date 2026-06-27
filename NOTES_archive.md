# NOTES_archive.md — compacted decision/verification detail (git-tracked; NEVER read on resume)

> Moved out of `NOTES.md` per the Compaction Rule (2026-06-27, after Stage 5 ✅). These are the
> per-stage "IMPLEMENTED & PM-verified" verification narratives — all re-fetchable from `FACTS.md`,
> the `handbacks/stage-*.md` files, and the git tags. The live `NOTES.md` keeps the decisions (the
> *why*), the handback pointers, and the open follow-ups.

## D-S5 status (2026-06-27) — IMPLEMENTED & PM-verified
Additive schema fields (`ResponseDocItem.sensitivities`, `review_approved`) + 2 §5.1 reason-codes
(`SENSITIVITY_HOLD`, `EXTERNAL_SEND_BLOCKED`) landed in code AND synced into `CLAUDE.md` §9.
PM independently verified: append-only audit + redaction (raw key/email/phone → placeholders);
APPROVED-only Markdown+CSV export; sensitivity gate holds internal/restricted unless review_approved;
byte-exact `REVIEW_BANNER`; AST-grep proof that `export.py` has zero network primitives
(`__future__/app/csv/io/pathlib` only); import creates no `audit/`/`exports/` dir. Documented
non-issues (not defects): redaction scoped to `detail` (deliberate); the affirmative export event
reuses `EXTERNAL_SEND_BLOCKED` as a compliance marker per the §5.1 mapping.

## D-S4 status (2026-06-27) — IMPLEMENTED & PM-verified
The 5 new constants landed in `app/config.py` and synced into `CLAUDE.md` §9 (`DEFAULT_REVIEWER_QUEUE`
+ 4 §5.1 reason-codes). Confidence number verified model-independent + invariant to rationale; routing
precedence + queue-from-policy-map verified; state machine blocks agent self-approve
(`SELF_APPROVE_BLOCKED`) and allows `actor="human"`. Real-data routing characterized (FACTS "demo
routing"): case_confident i1/i2 = clean auto-drafts; case_review = ROUTED_HIGH_RISK→legal.

## D-S3 status (2026-06-27) — IMPLEMENTED & PM-verified
The two new constants landed in `app/config.py` and synced into `CLAUDE.md` §9
(`GROUNDING_COVERAGE_MIN=0.5`; `GROUNDING_FAIL`). Grounding gate verified by PM across all three
ungrounded conditions (no citation / fabricated id / low coverage). Known limitation (not a defect):
the gate is lexical coverage, not semantic — a draft could pass by echoing chunk tokens; the live lane
+ mandatory human review are the backstop.
