# FACTS.md — Verified-Facts Ledger

Project: **Alta Outbound Voice Agent (codename: "Aria")**
Maintained by: Asaf (PM)

> **The ONLY place a hard number/metric lives.** Every other file — `PLAN.md` status cells,
> `NOTES.md` / `PM_LOG.md` entries, `STATE.md`'s `Live-truth` snapshot, scripts, the video script —
> **references a fact by name and never restates the literal value**. When a value changes, edit the
> one row here; the pointers don't move.
>
> A fact enters this ledger **only after it has been verified by running its source-of-truth command**
> — never copied from a draft or a handback. Re-verify before relying on any row (per the methodology's
> "never report a number you haven't verified" rule). `STATE.md` numbers are a re-verify-me snapshot,
> not an authority — this file is the authority.

| Fact | Value | Source-of-truth command | Verified | Commit |
|---|---|---|---|---|
| offline suite | 543 pass / 1 skip / 1 xfail | `make test` | 2026-06-25 | 7bd51e1 |
| import-safety (ENV4) | clean from empty cwd, lazy singletons `None` | `python -c "import app.config, app.server, app.tools, app.orchestrate, app.budget, app.consent"` | 2026-06-25 | 7bd51e1 |
| eval book-rate A / B | 0.4 / 0.2 | `make eval` | 2026-06-25 | 7bd51e1 |
| eval disclosure / objection / compliance | 0.8 / 1.0 / 1.0 (both arms) | `make eval` | 2026-06-25 | 7bd51e1 |
| eval avg turns A / B | 3.4 / 2.6 | `make eval` | 2026-06-25 | 7bd51e1 |
| cumulative spend | $0.81 / $50 cap | budget ledger (`app/budget.py`) | 2026-06-25 | 7bd51e1 |
| live calls used | 2 / 6 (`MAX_LIVE_CALLS`) | budget ledger | 2026-06-25 | 7bd51e1 |
| live demo call cost (`019ef8f2`) | $0.1482 | receipt under `receipts/` | 2026-06-25 | 7bd51e1 |
| live turn latency (post-tune, `019efe63`) | 1720 ms (model 559 / voice 304) | Vapi `performanceMetrics` | 2026-06-25 | 7bd51e1 |

**Skip / xfail provenance:** the 1 skip = live-only barge-in `STR-T1`; the 1 xfail = the Bug-1
re-offer end-to-end guard (`STR-L11`), `xfail` until the re-offer loop lands.

**Caps referenced by name (defined once in `CLAUDE.md` §9, not restated as numbers elsewhere):**
`HARD_BUDGET_USD`, `LIVE_CALL_BUDGET_USD`, `MAX_COST_PER_CALL_USD`, `MAX_LIVE_CALLS`,
`MAX_LIVE_STRESS_CALLS`, `MAX_CALL_DURATION_S`, `MAX_AGENT_TURNS`, `DAILY_CALL_CAP`,
`BOOKING_SLOT_MINUTES`, `BOOKING_LOOKAHEAD_DAYS`, `RANDOM_SEED`.
