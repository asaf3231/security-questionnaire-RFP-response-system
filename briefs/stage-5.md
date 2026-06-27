# Brief — Stage 5: Audit log + export + hard boundary

Read first (in order): `CLAUDE.md` (esp. §5 `RULE_AUDIT_COMPLETE`/`RULE_NO_EXTERNAL_SEND`/
`RULE_SENSITIVITY_GATE`, §7) → `PLAN.md` (Stage 5) → `QA_checklist.md` (`AUDIT1`–`AUDIT3`,
`EXPORT1`–`EXPORT3`, `BOUND1`–`BOUND2`) → `NOTES.md` (D-S5), then this brief.

Goal: the append-only JSONL audit trail (with redaction), the local-disk-only Markdown+CSV export
gated to APPROVED items, and the two hard boundaries (`RULE_NO_EXTERNAL_SEND`, `RULE_SENSITIVITY_GATE`).
Fully offline + deterministic.

## Scope — do ONLY this stage

### 0. Additive contract changes (PM is surfacing to Asaf — additive only; do NOT alter existing fields/values)
- `app/schema.py` — add to `ResponseDocItem`: `sensitivities: list[str] = Field(default_factory=list)`
  and `review_approved: bool = False`. (No existing field changed.)
- `app/config.py` — materialize the §5.1 reason-codes this stage needs:
  `SENSITIVITY_HOLD = "SENSITIVITY_HOLD"`, `EXTERNAL_SEND_BLOCKED = "EXTERNAL_SEND_BLOCKED"`.

### 1. `app/audit.py` — append-only JSONL audit logger (graded; `RULE_AUDIT_COMPLETE`; `AUDIT1`–`AUDIT3`)
- `def new_audit_event(*, questionnaire_id, item_id, event, from_state=None, to_state=None, rule=None,
  detail=None, timestamp=None) -> AuditEvent` — builds a validated `AuditEvent`; `timestamp` defaults
  to `datetime.now(timezone.utc).isoformat()` (allow injection for deterministic tests).
- `def write_audit(event: AuditEvent, *, log_path: Path | None = None) -> Path` — appends **exactly
  one** JSONL line (`json.dumps` of the redacted event dict + "\n") in `"a"` mode; default
  `log_path = <repo>/audit/audit.jsonl` (create `audit/` lazily with `mkdir(parents=True,
  exist_ok=True)`; **never at import**). Returns the path. Append-only — never rewrites/truncates.
- `def redact(obj)` — recursively redact strings in the event's `detail` (and any string field) BEFORE
  writing: `sk-ant-[A-Za-z0-9_-]{20,}` → `[REDACTED-SECRET]`; `ANTHROPIC_API_KEY=<value>` → redacted;
  emails → `[REDACTED-EMAIL]`; long digit runs / E.164 phones → `[REDACTED-PHONE]`. Use named regex
  constants (no inline magic). `RULE_NO_SECRET`/`RULE_NO_REAL_PII` cross-check (`AUDIT3`).
- `AUDIT1`: N `write_audit` calls → exactly N lines (one event per call; the pipeline at Stage 6 calls
  it per transition/tool — here prove the writer is 1-line-per-call with no gap/dupe).
- `AUDIT2`: every written line parses back to a valid `AuditEvent`; file is append-only (a second
  write preserves the first line).
- `AUDIT3`: an event whose `detail` carries a fake `sk-ant-…` key / an email / a phone → the written
  line contains the redaction placeholders, not the raw values.
- Import-safe: no file written / no dir created at import.

### 2. `app/export.py` — local Markdown + CSV export (graded; `EXPORT1`–`EXPORT3`)
- `def render_markdown(items: list[ResponseDocItem]) -> str` and
  `def render_csv(items: list[ResponseDocItem]) -> str` — CSV columns: `item_id, question, status,
  confidence_score, queue, citations` (citations = `;`-joined chunk_ids). Use the stdlib `csv` module.
- `def render_preview(doc: ResponseDoc) -> str` — render ALL items for human view; if ANY item's
  `status != "APPROVED"`, **prepend the byte-exact `REVIEW_BANNER`** (from config) as the first line
  (`EXPORT3`).
- `def export_response(doc: ResponseDoc, *, out_dir: Path | None = None, log_path: Path | None = None)
  -> dict[str, Path]` — the final extraction:
  - **Exportable filter (`EXPORT1`/`BOUND2`):** keep only items with `status == "APPROVED"`.
  - **Sensitivity gate (`EXPORT2`/`RULE_SENSITIVITY_GATE`):** if an item's `sensitivities ∩
    {"internal","restricted"}` and NOT `review_approved` → **hold it** (exclude from export) and
    `write_audit(... rule=RULE_SENSITIVITY_GATE, detail includes SENSITIVITY_HOLD ...)`. Non-sensitive
    APPROVED items, and sensitive items with `review_approved=True`, export normally.
  - Write `exports/<questionnaire_id>.md` + `exports/<questionnaire_id>.csv` (default `out_dir =
    <repo>/exports`, created lazily; **local disk only**).
  - `write_audit(... event="export", rule=RULE_NO_EXTERNAL_SEND, detail={"destination":"local_disk",
    "paths":[...], "exported": n, "held": m})` — the affirmative local-only record.
  - Return `{"markdown": <path>, "csv": <path>}`.

### 3. Hard boundary (`RULE_NO_EXTERNAL_SEND`; `BOUND1`–`BOUND2`)
- **There is NO network/send capability in `app/export.py`** — do not import or use `socket`,
  `smtplib`, `urllib`, `http.client`, `requests`, `httpx`, `ftplib`, or any send primitive. (A test
  greps `app/export.py` source for these and asserts zero hits — `BOUND1`.)
- `BOUND2`: a non-APPROVED item never appears in either export file (the filter guarantees it);
  cross-checks `RULE_NO_SELF_APPROVE` (only human-APPROVED items export).

### 4. Tests (`AUDIT1`–`AUDIT3`, `EXPORT1`–`EXPORT3`, `BOUND1`–`BOUND2`) + progressive ENV4
Use `tmp_path` for all file writes (never write into the real `audit/`/`exports/` during tests).
Add `app.audit`, `app.export` to the ENV4-progressive test (addition).

## QA checks to PASS (run, not inspect): `AUDIT1`–`AUDIT3`, `EXPORT1`–`EXPORT3`, `BOUND1`–`BOUND2` (+ `make test` green; `ENV4` clean)

## Constraints (from CLAUDE.md)
- Append-only audit; **no secret/real PII in any audit line** (redaction layer); byte-exact
  `REVIEW_BANNER` from config.
- **No external send anywhere** — export is local-disk-only, post-APPROVED (`RULE_NO_EXTERNAL_SEND`).
- Import-safe (no file/dir at import); deterministic; no inline magic values (reason-codes/literals/
  regex are named constants).

## Do NOT
- Touch the spine docs (PM-owned). Adding the 2 schema fields + 2 config reason-codes IS in scope; do
  NOT change any EXISTING schema field, §9 constant value, byte-exact literal, or `RULE_*`.
- Change the `write_audit`/`new_audit_event`/`redact`/`export_response`/`render_*` signatures above —
  surface as DECISION-NEEDED.
- Implement the pipeline orchestration or the demo runner — Stage 6. (Export/audit just provide the
  functions; the per-transition audit emission across a full run is wired in Stage 6.)
- Modify an existing graded test to make it pass (verifier-independence). Adding new tests / ENV4
  modules is fine. Do not commit.

## Deliver
Write `handbacks/stage-5.md` (CLAUDE §12.1 format). Report: `make test` pass/skip count, files
created/modified (call out the 2 schema fields + 2 config reason-codes), each `AUDIT*`/`EXPORT*`/
`BOUND*` ✅/⚠️ (test-verified), confirmation `REVIEW_BANNER` byte-exact + redaction works + NO network
primitive in `export.py`, any DECISION-NEEDED, one next action. Return it as your final message. The PM
re-runs the checks, independently greps `export.py` for send primitives + verifies the sensitivity gate
+ redaction, runs `/code-review`, and records in `FACTS.md`.
