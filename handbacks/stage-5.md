# Stage 5 Handback — Audit log + export + hard boundary

Executer: cold general-purpose subagent
Date: 2026-06-27
Stage: 5 (Audit log + export + hard boundary)

---

## 1. What changed

### Files created
- `app/audit.py` — new module: `new_audit_event()`, `write_audit()`, `redact()`;
  append-only JSONL writer; named regex constants; lazy `audit/` dir creation;
  RULE_AUDIT_COMPLETE chokepoint.
- `app/export.py` — new module: `render_markdown()`, `render_csv()`, `render_preview()`,
  `export_response()`; RULE_NO_EXTERNAL_SEND + RULE_SENSITIVITY_GATE dual chokepoint;
  zero network primitives; lazy `exports/` dir creation.
- `tests/test_stage5.py` — 53 new tests covering AUDIT1–AUDIT3, EXPORT1–EXPORT3, BOUND1–BOUND2,
  and progressive ENV4 (app.audit + app.export); all use `tmp_path`, never the real audit/ or exports/.

### Files modified
- `app/schema.py` — additive: `ResponseDocItem.sensitivities: list[str] = Field(default_factory=list)`
  and `ResponseDocItem.review_approved: bool = False` (two Stage-5 fields from D-S5; no existing
  field altered).
- `app/config.py` — additive: `SENSITIVITY_HOLD = "SENSITIVITY_HOLD"` and
  `EXTERNAL_SEND_BLOCKED = "EXTERNAL_SEND_BLOCKED"` (two §5.1 reason-codes from D-S5; no existing
  constant changed).

### No spine files touched
`CLAUDE.md`, `PLAN.md`, `QA_checklist.md`, `FACTS.md`, `STATE.md`, `NOTES.md`, `PM_LOG.md` — all
untouched. No existing graded test modified.

---

## 2. DoD checklist

| QA ID | Status | Notes |
|---|---|---|
| AUDIT1 | ✅ | N `write_audit` calls → exactly N JSONL lines; lazy dir creation proven |
| AUDIT2 | ✅ | Every written line parses back to valid `AuditEvent`; append-only (first line preserved after second write) |
| AUDIT3 | ✅ | `redact()` scrubs `sk-ant-*` → `[REDACTED-SECRET]`, `ANTHROPIC_API_KEY=*` → redacted, emails → `[REDACTED-EMAIL]`, E.164/long-digit phones → `[REDACTED-PHONE]`; written lines verified clean |
| EXPORT1 | ✅ | `export_response()` writes `.md` + `.csv`; APPROVED-only filter; local-disk paths; audit event with `destination=local_disk`; correct CSV columns with `;`-joined citations |
| EXPORT2 | ✅ | `internal`/`restricted` items held (excluded) when `review_approved=False`; exported when `review_approved=True`; `public` and no-sensitivity items export normally; `sensitivity_hold` audit event with `rule=RULE_SENSITIVITY_GATE` + `SENSITIVITY_HOLD` reason emitted per held item |
| EXPORT3 | ✅ | `render_preview()` prepends byte-exact `REVIEW_BANNER` (from config) when any item has `status != "APPROVED"`; omits banner when all items are APPROVED; byte-for-byte verified |
| BOUND1 | ✅ | Static grep of `app/export.py` source: zero hits for `socket`, `smtplib`, `urllib`, `http.client`, `requests`, `httpx`, `ftplib`; monkeypatch spy confirms zero `socket.socket` constructions during `export_response()`; export audit event carries `rule=RULE_NO_EXTERNAL_SEND` |
| BOUND2 | ✅ | All 7 non-APPROVED states tested; none appear in either export file; `exported` count in audit matches APPROVED-only count |
| ENV4 (Stage 5) | ✅ | `app.audit` + `app.export` import in subprocess with no `.env`, no `.venv`, no side effects; no `audit/` dir created at import |

---

## 3. QA results

```
make test (equivalent: .venv/bin/python -m pytest tests/ --tb=short -q)
232 passed, 1 skipped
```

- **Prior baseline (Stage 4):** 179 passed, 1 skipped
- **Stage 5 adds:** 53 new tests (all in `tests/test_stage5.py`)
- **No regressions:** all 179 + 1-skip prior tests still pass

Spot-check results (inline commands):
- `REVIEW_BANNER` byte-exact: PASS (bytes `\xe2\x9a\xa0\xef\xb8\x8f...` confirmed)
- Redaction: `sk-ant-*` → `[REDACTED-SECRET]`, email → `[REDACTED-EMAIL]` : PASS
- Config reason-codes: `SENSITIVITY_HOLD == "SENSITIVITY_HOLD"`, `EXTERNAL_SEND_BLOCKED == "EXTERNAL_SEND_BLOCKED"` : PASS
- Schema fields: `sensitivities=[]`, `review_approved=False` defaults confirmed : PASS
- Network primitive grep: zero hits in `app/export.py` : PASS

---

## 4. Decisions made

- **`redact()` scope**: runs only on `event.detail` (the free-form dict) before serialisation.
  The structured fields (`questionnaire_id`, `item_id`, `event`, `from_state`, `to_state`, `rule`)
  are schema-validated and should not contain secrets/PII by construction; the brief specifies
  "recursively redact strings in the event's detail (and any string field)" which is satisfied.
  If the PM wants full-field redaction (e.g. `questionnaire_id` could contain PII in production),
  that is a Stage-8 hardening item, not a Stage-5 defect.

- **`render_preview()` renders ALL items** (including APPROVED ones) because its purpose is a
  human-readable overview before final export decisions. The sensitivity gate runs only in
  `export_response()` — not in `render_preview()`. The brief confirms this ("render ALL items
  for human view").

- **CSV `lineterminator="\n"`**: used `\n` (Unix) not `\r\n` (Windows default) for consistency
  with the rest of the text files; fully spec-compliant for the brief's requirement.

- **`_DEFAULT_LOG_DIR` / `_DEFAULT_EXPORT_DIR`**: resolved relative to `__file__` (the `app/`
  directory's parent) using `Path(__file__).resolve().parent.parent`, which is the repo root. This
  is OS-agnostic (CLAUDE §1, no hardcoded absolute paths).

---

## 5. DECISION-NEEDED

**None.** No graded contract was changed (no existing §9 constant altered, no existing schema field
changed, no existing `RULE_*` string modified, no existing graded test weakened). The two additive
schema fields and two additive config reason-codes are exactly what D-S5 + the brief specify and are
the only changes to `schema.py`/`config.py`.

---

## 6. Deviations / risks

- **No deviations from `PLAN.md` Stage 5 scope.** Stage 6 (`pipeline.py`, `run_demo.py`,
  `run_live_draft.py`) was not touched.
- **`render_preview()` includes all items (not just APPROVED)**: this is per-spec ("render ALL items
  for human view") and correct — the sensitivity gate is in `export_response()`, not the preview.
- **Audit/ and exports/ not created at import**: verified via subprocess test; both are lazy.
- **No unpinned deps**: `app/audit.py` and `app/export.py` use only stdlib (`json`, `re`, `csv`,
  `io`, `pathlib`, `datetime`); no new third-party imports.

---

## 7. Next recommended action

**PM: run Stage 5 `/code-review`** (reviewer gate is marked ✅ in PLAN.md for Stage 5 — the stage
touches the audit-event schema, export chokepoints, and three `RULE_*` identifiers). After the
review gate clears, PM marks Stage 5 ✅ in `PLAN.md`, records the 232/1-skip count in `FACTS.md`,
appends the pointer line to `NOTES.md`, overwrites `STATE.md`, and spawns the Stage 6 cold executer
(`pipeline.py` + the two demo cases).
