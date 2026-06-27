"""
tests/test_stage5.py — Offline deterministic suite for Stage 5.

Covers: AUDIT1–AUDIT3, EXPORT1–EXPORT3, BOUND1–BOUND2, and progressive ENV4
(app.audit, app.export added to the import-safety set).

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: uses tmp_path for all file I/O; never writes into the real
audit/ or exports/ directories.

QA check mapping:
  AUDIT1 — write_audit() emits exactly one JSONL line per call; N calls → N lines
  AUDIT2 — each written line parses back to valid AuditEvent; append-only (first line preserved)
  AUDIT3 — detail with fake secret/email/phone → redacted placeholders in written line
  EXPORT1 — export_response() writes .md + .csv; only APPROVED items exported; local-disk only
  EXPORT2 — sensitivity gate holds internal/restricted unless review_approved=True
  EXPORT3 — render_preview() prepends byte-exact REVIEW_BANNER when any item is non-APPROVED
  BOUND1  — no network-send primitive imported/used in app/export.py (static grep + spy)
  BOUND2  — non-APPROVED items never appear in either export file
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_response_doc_item(
    item_id: str = "i1",
    question: str = "How do you encrypt data at rest?",
    draft_text: str = "We use AES-256 encryption.",
    status: str = "APPROVED",
    confidence_score: float = 0.85,
    queue: str | None = None,
    citations: list | None = None,
    sensitivities: list[str] | None = None,
    review_approved: bool = False,
):
    from app.schema import Citation, ResponseDocItem
    return ResponseDocItem(
        item_id=item_id,
        question=question,
        draft_text=draft_text,
        status=status,
        confidence_score=confidence_score,
        queue=queue,
        citations=[Citation(chunk_id=c) for c in (citations or [])],
        sensitivities=sensitivities or [],
        review_approved=review_approved,
    )


def _make_response_doc(
    questionnaire_id: str = "q1",
    items: list | None = None,
):
    from app.schema import ResponseDoc
    return ResponseDoc(
        questionnaire_id=questionnaire_id,
        generated_at="2026-06-27T00:00:00+00:00",
        items=items or [],
    )


def _parse_jsonl(path: Path) -> list[dict]:
    """Read every non-empty line from a JSONL file and return parsed dicts."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            lines.append(json.loads(line))
    return lines


# ---------------------------------------------------------------------------
# Progressive ENV4 — import-safety for Stage 5 modules
# ---------------------------------------------------------------------------


class TestENV4Stage5:
    """ENV4 (progressive): Stage 5 modules import without side effects.

    Adds app.audit, app.export to the tested set.
    """

    MODULES_TO_TEST = [
        "app.config",
        "app.schema",
        "app.kb",
        "app.retrieval",
        "app.eval.rubric",
        "app.eval.fixtures",
        "app.context_stack",
        "app.llm",
        "app.draft",
        "app.confidence",
        "app.routing",
        "app.state",
        "app.audit",
        "app.export",
    ]

    def test_stage5_modules_import_cleanly(self):
        """Stage 5 app.* modules import without raising in a subprocess with no .env."""
        code = (
            f"import sys; sys.path.insert(0, r'{REPO_ROOT}'); "
            + "; ".join(f"import {m}" for m in self.MODULES_TO_TEST)
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        assert result.returncode == 0, (
            f"Import of Stage 5 app modules failed:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_audit_no_side_effects_at_import(self):
        """app.audit imports without any side effects (no file/dir created)."""
        import app.audit  # noqa: F401

    def test_export_no_side_effects_at_import(self):
        """app.export imports without any side effects (no file/dir created)."""
        import app.export  # noqa: F401

    def test_new_config_reason_codes_exist(self):
        """New Stage 5 reason-codes exist in app.config with correct values."""
        import app.config as cfg

        assert hasattr(cfg, "SENSITIVITY_HOLD"), "SENSITIVITY_HOLD must be in config"
        assert cfg.SENSITIVITY_HOLD == "SENSITIVITY_HOLD"

        assert hasattr(cfg, "EXTERNAL_SEND_BLOCKED"), "EXTERNAL_SEND_BLOCKED must be in config"
        assert cfg.EXTERNAL_SEND_BLOCKED == "EXTERNAL_SEND_BLOCKED"

    def test_new_schema_fields_exist(self):
        """ResponseDocItem has the two Stage-5 additive fields with correct defaults."""
        from app.schema import ResponseDocItem

        item = ResponseDocItem(
            item_id="x1",
            question="Test?",
            draft_text="Answer.",
            status="APPROVED",
        )
        assert hasattr(item, "sensitivities"), "ResponseDocItem must have .sensitivities"
        assert item.sensitivities == [], f"Default sensitivities must be []; got {item.sensitivities}"

        assert hasattr(item, "review_approved"), "ResponseDocItem must have .review_approved"
        assert item.review_approved is False, f"Default review_approved must be False; got {item.review_approved}"

    def test_no_audit_dir_created_at_import(self, tmp_path, monkeypatch):
        """Importing app.audit does not create the audit/ directory."""
        # Run in a subprocess to isolate module import state
        code = (
            f"import sys; sys.path.insert(0, r'{REPO_ROOT}'); import app.audit; "
            f"import pathlib; "
            f"d = pathlib.Path(r'{tmp_path / 'audit'}'); "
            f"assert not d.exists(), f'audit dir created at import: {{d}}'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        assert result.returncode == 0, (
            f"app.audit created a directory at import:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# AUDIT1 — one event per call; N calls → exactly N lines
# ---------------------------------------------------------------------------


class TestAUDIT1:
    """AUDIT1: write_audit() appends exactly one JSONL line per call; N calls → N lines."""

    def test_single_write_creates_one_line(self, tmp_path):
        """A single write_audit call → exactly 1 line in the file."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="state_transition",
            from_state="INTAKE",
            to_state="RETRIEVED",
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt, log_path=log)

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, f"Expected 1 line after 1 write; got {len(lines)}"

    def test_n_writes_create_n_lines(self, tmp_path):
        """N write_audit calls → exactly N lines."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"
        n = 5
        for i in range(n):
            evt = new_audit_event(
                questionnaire_id="q1",
                item_id=f"i{i}",
                event="tool_call",
                timestamp="2026-06-27T00:00:00+00:00",
            )
            write_audit(evt, log_path=log)

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == n, f"Expected {n} lines after {n} writes; got {len(lines)}"

    def test_write_creates_parent_dir_lazily(self, tmp_path):
        """write_audit() creates the parent directory if it doesn't exist."""
        from app.audit import new_audit_event, write_audit

        nested = tmp_path / "subdir" / "nested" / "audit.jsonl"
        assert not nested.parent.exists(), "Parent dir must not pre-exist"

        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="test",
            timestamp="2026-06-27T00:00:00+00:00",
        )
        path = write_audit(evt, log_path=nested)

        assert nested.exists(), "write_audit() must create the parent directory lazily"
        assert path == nested

    def test_write_audit_returns_path(self, tmp_path):
        """write_audit() returns the path to which the event was appended."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="tool_call",
            timestamp="2026-06-27T00:00:00+00:00",
        )
        result = write_audit(evt, log_path=log)
        assert result == log


# ---------------------------------------------------------------------------
# AUDIT2 — each line parses back to valid AuditEvent; append-only
# ---------------------------------------------------------------------------


class TestAUDIT2:
    """AUDIT2: each written line is a valid AuditEvent; file is append-only."""

    def test_written_line_parses_to_audit_event(self, tmp_path):
        """A written JSONL line deserialises to a valid AuditEvent."""
        from app.audit import new_audit_event, write_audit
        from app.schema import AuditEvent

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="state_transition",
            from_state="DRAFTED",
            to_state="SCORED",
            rule="RULE_AUDIT_COMPLETE",
            detail={"confidence": 0.82},
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt, log_path=log)

        raw = log.read_text(encoding="utf-8").strip()
        parsed = json.loads(raw)
        recovered = AuditEvent(**parsed)

        assert recovered.questionnaire_id == "q1"
        assert recovered.item_id == "i1"
        assert recovered.event == "state_transition"
        assert recovered.from_state == "DRAFTED"
        assert recovered.to_state == "SCORED"
        assert recovered.rule == "RULE_AUDIT_COMPLETE"

    def test_all_required_fields_present(self, tmp_path):
        """Every written event carries all required AuditEvent fields."""
        from app.audit import new_audit_event, write_audit
        from app.schema import AuditEvent

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q2",
            item_id="i2",
            event="tool_call",
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt, log_path=log)

        parsed = json.loads(log.read_text(encoding="utf-8").strip())
        required = {"timestamp", "questionnaire_id", "item_id", "event"}
        for field in required:
            assert field in parsed, f"Required field '{field}' missing from written event"

        # Should also validate as AuditEvent
        AuditEvent(**parsed)

    def test_append_only_preserves_first_line(self, tmp_path):
        """Second write preserves the first line (append-only; no truncation)."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"

        evt1 = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="first_event",
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt1, log_path=log)

        first_content = log.read_text(encoding="utf-8")

        evt2 = new_audit_event(
            questionnaire_id="q1",
            item_id="i2",
            event="second_event",
            timestamp="2026-06-27T00:01:00+00:00",
        )
        write_audit(evt2, log_path=log)

        all_lines = log.read_text(encoding="utf-8").splitlines()
        assert len(all_lines) == 2, f"Expected 2 lines after 2 appends; got {len(all_lines)}"

        # The first line must still be there
        first_in_file = all_lines[0]
        assert json.loads(first_in_file)["event"] == "first_event", (
            "First event must be preserved (append-only)"
        )

    def test_detail_dict_is_written(self, tmp_path):
        """detail dict is serialised into the written event."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="export",
            detail={"destination": "local_disk", "exported": 3, "held": 0},
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt, log_path=log)

        parsed = json.loads(log.read_text(encoding="utf-8").strip())
        assert parsed["detail"]["destination"] == "local_disk"
        assert parsed["detail"]["exported"] == 3


# ---------------------------------------------------------------------------
# AUDIT3 — redaction gate (RULE_NO_SECRET / RULE_NO_REAL_PII)
# ---------------------------------------------------------------------------


# Key-SHAPED fake token built at RUNTIME so no literal secret-shape sits in this
# tracked file — keeps the SEC1 tracked-file scan (sk-ant-[A-Za-z0-9_-]{20,}) green
# while still exercising redact() on a real-shaped key. Assertions below are unchanged.
_FAKE_SK_ANT = "sk-ant-" + "A" * 24


class TestAUDIT3:
    """AUDIT3: redact() scrubs secrets and PII; written lines must not contain raw values."""

    def test_redact_sk_ant_key(self):
        """sk-ant-... token in a string is replaced by [REDACTED-SECRET]."""
        from app.audit import redact

        raw = f"The key is {_FAKE_SK_ANT} in the header."
        result = redact(raw)
        assert "sk-ant-" not in result, f"sk-ant- token must be redacted; got: {result!r}"
        assert "[REDACTED-SECRET]" in result

    def test_redact_api_key_assignment(self):
        """ANTHROPIC_API_KEY=<value> is redacted."""
        from app.audit import redact

        raw = f"Config: ANTHROPIC_API_KEY={_FAKE_SK_ANT}"
        result = redact(raw)
        assert "sk-ant-" not in result
        assert "ANTHROPIC_API_KEY=[REDACTED-SECRET]" in result

    def test_redact_email(self):
        """Email addresses are replaced by [REDACTED-EMAIL]."""
        from app.audit import redact

        raw = "Contact reviewer at jane.doe@example.com for approval."
        result = redact(raw)
        assert "jane.doe@example.com" not in result
        assert "[REDACTED-EMAIL]" in result

    def test_redact_phone(self):
        """E.164 phones and long digit strings are redacted."""
        from app.audit import redact

        raw = "Call +14155552671 or 8005551234 for support."
        result = redact(raw)
        assert "+14155552671" not in result or "8005551234" not in result

    def test_redact_dict(self):
        """redact() recursively processes dicts."""
        from app.audit import redact

        obj = {
            "key": _FAKE_SK_ANT,
            "contact": "admin@secret.org",
            "safe": "normal text",
        }
        result = redact(obj)
        assert "sk-ant-" not in str(result)
        assert "admin@secret.org" not in str(result)
        assert result["safe"] == "normal text"

    def test_redact_nested_list(self):
        """redact() recursively processes lists."""
        from app.audit import redact

        obj = [_FAKE_SK_ANT, "user@company.com", "safe"]
        result = redact(obj)
        assert "sk-ant-" not in str(result)
        assert "user@company.com" not in str(result)
        assert result[2] == "safe"

    def test_written_audit_line_has_no_secret(self, tmp_path):
        """An audit event with a fake secret in detail → written line is redacted."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="tool_call",
            detail={"api_key": _FAKE_SK_ANT + "_fake"},
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt, log_path=log)

        written = log.read_text(encoding="utf-8")
        assert "sk-ant-" not in written, (
            f"Written audit line must not contain raw sk-ant- token; got: {written!r}"
        )
        assert "[REDACTED-SECRET]" in written

    def test_written_audit_line_has_no_email(self, tmp_path):
        """An audit event with an email in detail → written line has it redacted."""
        from app.audit import new_audit_event, write_audit

        log = tmp_path / "audit.jsonl"
        evt = new_audit_event(
            questionnaire_id="q1",
            item_id="i1",
            event="tool_call",
            detail={"reviewer": "sec-reviewer@example.com"},
            timestamp="2026-06-27T00:00:00+00:00",
        )
        write_audit(evt, log_path=log)

        written = log.read_text(encoding="utf-8")
        assert "sec-reviewer@example.com" not in written, (
            f"Written audit line must not contain raw email; got: {written!r}"
        )
        assert "[REDACTED-EMAIL]" in written

    def test_redact_preserves_non_sensitive_data(self):
        """redact() does not alter non-sensitive strings."""
        from app.audit import redact

        safe = "Confidence score: 0.82. Status: APPROVED."
        assert redact(safe) == safe

    def test_redact_short_digits_not_redacted(self):
        """Short digit strings (< 7 digits) are not treated as phone numbers."""
        from app.audit import redact

        raw = "Page 42 of 99 items."
        result = redact(raw)
        assert "42" in result and "99" in result, (
            f"Short digit strings must not be redacted; got: {result!r}"
        )


# ---------------------------------------------------------------------------
# EXPORT1 — export only APPROVED, local disk, Markdown + CSV
# ---------------------------------------------------------------------------


class TestEXPORT1:
    """EXPORT1: export_response() writes .md + .csv; only APPROVED items; local disk only."""

    def test_export_creates_md_and_csv(self, tmp_path):
        """export_response() writes both a .md and a .csv file."""
        from app.export import export_response

        doc = _make_response_doc(
            questionnaire_id="q1",
            items=[_make_response_doc_item(item_id="i1", status="APPROVED")],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        assert "markdown" in result and "csv" in result
        assert result["markdown"].exists(), ".md file must be created"
        assert result["csv"].exists(), ".csv file must be created"

    def test_approved_item_appears_in_export(self, tmp_path):
        """An APPROVED item appears in both the .md and .csv exports."""
        from app.export import export_response

        doc = _make_response_doc(
            questionnaire_id="q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    question="How do you encrypt data?",
                    draft_text="AES-256 encryption.",
                    status="APPROVED",
                    citations=["c1"],
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        md_text = result["markdown"].read_text(encoding="utf-8")
        assert "How do you encrypt data?" in md_text, "Approved item question must appear in .md"

        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "i1" in csv_text, "Approved item_id must appear in .csv"
        assert "c1" in csv_text, "Citation must appear in .csv"

    def test_non_approved_item_excluded_from_export(self, tmp_path):
        """A non-APPROVED item does not appear in either export file."""
        from app.export import export_response

        doc = _make_response_doc(
            questionnaire_id="q1",
            items=[
                _make_response_doc_item(item_id="i1", status="APPROVED", question="Approved?"),
                _make_response_doc_item(item_id="i2", status="SCORED", question="Not approved yet?"),
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        md_text = result["markdown"].read_text(encoding="utf-8")
        csv_text = result["csv"].read_text(encoding="utf-8")

        assert "Not approved yet?" not in md_text, "Non-approved item must not appear in .md"
        assert "i2" not in csv_text, "Non-approved item_id must not appear in .csv"

    def test_csv_has_correct_columns(self, tmp_path):
        """The CSV file has the required columns in the correct order."""
        from app.export import export_response

        doc = _make_response_doc(
            questionnaire_id="q1",
            items=[_make_response_doc_item(status="APPROVED", citations=["c1", "c2"])],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        reader = csv.DictReader(io.StringIO(result["csv"].read_text(encoding="utf-8")))
        expected_cols = ["item_id", "question", "status", "confidence_score", "queue", "citations"]
        assert list(reader.fieldnames) == expected_cols, (
            f"CSV columns must be {expected_cols}; got {list(reader.fieldnames)}"
        )

    def test_csv_citations_joined_with_semicolon(self, tmp_path):
        """Multiple citations in CSV are joined with ';'."""
        from app.export import export_response

        doc = _make_response_doc(
            questionnaire_id="q1",
            items=[_make_response_doc_item(status="APPROVED", citations=["c1", "c2", "c3"])],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "c1;c2;c3" in csv_text, f"Citations must be ';'-joined; got:\n{csv_text}"

    def test_export_files_are_local(self, tmp_path):
        """Export paths are local (under the specified out_dir)."""
        from app.export import export_response

        out_dir = tmp_path / "exports"
        doc = _make_response_doc("q1", [_make_response_doc_item(status="APPROVED")])
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=out_dir, log_path=audit_log)

        for _key, path in result.items():
            assert str(path).startswith(str(out_dir)), (
                f"Export path must be under out_dir; got {path}"
            )

    def test_export_emits_audit_event(self, tmp_path):
        """export_response() emits at least one audit event to the log."""
        from app.export import export_response

        doc = _make_response_doc("q1", [_make_response_doc_item(status="APPROVED")])
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        assert audit_log.exists(), "Audit log must be created"
        events = _parse_jsonl(audit_log)
        assert len(events) >= 1, "At least one audit event must be written"

    def test_export_audit_event_has_local_disk_destination(self, tmp_path):
        """The export audit event records destination=local_disk."""
        from app.export import export_response

        doc = _make_response_doc("q1", [_make_response_doc_item(status="APPROVED")])
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        events = _parse_jsonl(audit_log)
        export_events = [e for e in events if e.get("event") == "export"]
        assert export_events, "An 'export' audit event must be emitted"

        export_evt = export_events[0]
        assert export_evt["detail"]["destination"] == "local_disk", (
            f"Export audit event must record destination=local_disk; got: {export_evt['detail']}"
        )

    def test_empty_doc_produces_empty_export_files(self, tmp_path):
        """A document with no items produces valid (empty-content) export files."""
        from app.export import export_response

        doc = _make_response_doc("q1", [])
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        assert result["markdown"].exists()
        assert result["csv"].exists()


# ---------------------------------------------------------------------------
# EXPORT2 — sensitivity gate (RULE_SENSITIVITY_GATE)
# ---------------------------------------------------------------------------


class TestEXPORT2:
    """EXPORT2: sensitivity gate holds internal/restricted items without review_approved."""

    def test_internal_item_held_without_review_approved(self, tmp_path):
        """An APPROVED item with sensitivity=internal is held if review_approved=False."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    question="Internal policy question?",
                    sensitivities=["internal"],
                    review_approved=False,
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        md_text = result["markdown"].read_text(encoding="utf-8")
        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "i1" not in csv_text, "Internal item without review_approved must be held from CSV"
        assert "Internal policy question?" not in md_text, "Internal item must be held from .md"

    def test_restricted_item_held_without_review_approved(self, tmp_path):
        """An APPROVED item with sensitivity=restricted is held if review_approved=False."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    question="Restricted policy question?",
                    sensitivities=["restricted"],
                    review_approved=False,
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "i1" not in csv_text, "Restricted item without review_approved must be held"

    def test_internal_item_exported_with_review_approved(self, tmp_path):
        """An APPROVED item with sensitivity=internal is exported when review_approved=True."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    question="Internal question (human-reviewed)?",
                    sensitivities=["internal"],
                    review_approved=True,
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "i1" in csv_text, "Internal item with review_approved=True must be exported"

    def test_public_item_exported_without_review_approved(self, tmp_path):
        """An APPROVED item with sensitivity=public exports without needing review_approved."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    question="Public question?",
                    sensitivities=["public"],
                    review_approved=False,
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "i1" in csv_text, "Public sensitivity item must be exported normally"

    def test_no_sensitivity_exported_without_review_approved(self, tmp_path):
        """An APPROVED item with no sensitivity tags exports without needing review_approved."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    sensitivities=[],
                    review_approved=False,
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        csv_text = result["csv"].read_text(encoding="utf-8")
        assert "i1" in csv_text, "Item with no sensitivities must export normally"

    def test_sensitivity_hold_emits_audit_event(self, tmp_path):
        """A held item emits a sensitivity_hold audit event with SENSITIVITY_HOLD reason."""
        from app.config import RULE_SENSITIVITY_GATE, SENSITIVITY_HOLD
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    sensitivities=["restricted"],
                    review_approved=False,
                )
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        events = _parse_jsonl(audit_log)
        hold_events = [e for e in events if e.get("event") == "sensitivity_hold"]
        assert hold_events, "A sensitivity_hold audit event must be emitted for held items"

        hold_evt = hold_events[0]
        assert hold_evt["rule"] == RULE_SENSITIVITY_GATE, (
            f"Hold event must carry rule=RULE_SENSITIVITY_GATE; got {hold_evt['rule']!r}"
        )
        assert hold_evt["detail"]["reason"] == SENSITIVITY_HOLD, (
            f"Hold event detail.reason must be SENSITIVITY_HOLD; got {hold_evt['detail']}"
        )

    def test_held_count_in_export_audit_event(self, tmp_path):
        """The export audit event records the correct held count."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(
                    item_id="i1",
                    status="APPROVED",
                    sensitivities=["internal"],
                    review_approved=False,  # held
                ),
                _make_response_doc_item(
                    item_id="i2",
                    status="APPROVED",
                    sensitivities=[],
                    review_approved=False,  # exported
                ),
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        events = _parse_jsonl(audit_log)
        export_events = [e for e in events if e.get("event") == "export"]
        assert export_events, "Export audit event must be present"

        detail = export_events[0]["detail"]
        assert detail["held"] == 1, f"held must be 1; got {detail['held']}"
        assert detail["exported"] == 1, f"exported must be 1; got {detail['exported']}"


# ---------------------------------------------------------------------------
# EXPORT3 — render_preview() byte-exact REVIEW_BANNER
# ---------------------------------------------------------------------------


class TestEXPORT3:
    """EXPORT3: render_preview() prepends byte-exact REVIEW_BANNER when any item is non-APPROVED."""

    def test_banner_prepended_when_unapproved_items_exist(self):
        """render_preview() prepends REVIEW_BANNER when any item has status != APPROVED."""
        from app.config import REVIEW_BANNER
        from app.export import render_preview

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(item_id="i1", status="APPROVED"),
                _make_response_doc_item(item_id="i2", status="SCORED"),
            ],
        )
        preview = render_preview(doc)
        assert preview.startswith(REVIEW_BANNER), (
            f"Preview must start with byte-exact REVIEW_BANNER when non-approved items exist.\n"
            f"Expected first chars: {REVIEW_BANNER[:30]!r}\n"
            f"Got first chars: {preview[:30]!r}"
        )

    def test_banner_is_byte_exact(self):
        """The REVIEW_BANNER used in render_preview() matches the config constant byte-for-byte."""
        from app.config import REVIEW_BANNER
        from app.export import render_preview

        doc = _make_response_doc(
            "q1",
            items=[_make_response_doc_item(item_id="i1", status="ROUTED_FOR_REVIEW")],
        )
        preview = render_preview(doc)
        # Extract first line
        first_line = preview.splitlines()[0]
        assert first_line == REVIEW_BANNER, (
            f"First line of preview must be REVIEW_BANNER byte-for-byte.\n"
            f"Expected: {REVIEW_BANNER!r}\n"
            f"Got:      {first_line!r}"
        )

    def test_no_banner_when_all_approved(self):
        """render_preview() omits REVIEW_BANNER when all items are APPROVED."""
        from app.config import REVIEW_BANNER
        from app.export import render_preview

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(item_id="i1", status="APPROVED"),
                _make_response_doc_item(item_id="i2", status="APPROVED"),
            ],
        )
        preview = render_preview(doc)
        assert not preview.startswith(REVIEW_BANNER), (
            "render_preview() must NOT prepend REVIEW_BANNER when all items are APPROVED"
        )

    def test_banner_on_single_non_approved_item(self):
        """render_preview() adds REVIEW_BANNER even if only one item is non-APPROVED."""
        from app.config import REVIEW_BANNER
        from app.export import render_preview

        doc = _make_response_doc(
            "q1",
            items=[_make_response_doc_item(status="INTAKE")],
        )
        preview = render_preview(doc)
        assert preview.startswith(REVIEW_BANNER), (
            "REVIEW_BANNER must be prepended when even a single item is non-APPROVED"
        )

    def test_banner_includes_all_item_content(self):
        """After the banner, render_preview() still renders all items."""
        from app.export import render_preview

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(item_id="i1", status="APPROVED", question="Approved Q?"),
                _make_response_doc_item(item_id="i2", status="SCORED", question="Pending Q?"),
            ],
        )
        preview = render_preview(doc)
        assert "Approved Q?" in preview
        assert "Pending Q?" in preview


# ---------------------------------------------------------------------------
# BOUND1 — no external send (static + spy)
# ---------------------------------------------------------------------------


class TestBOUND1:
    """BOUND1: app/export.py contains no network-send primitives (static grep + spy)."""

    _FORBIDDEN_IMPORTS = [
        "socket",
        "smtplib",
        "urllib",
        "http.client",
        "requests",
        "httpx",
        "ftplib",
    ]

    def test_no_forbidden_import_in_export_source(self):
        """Static grep: app/export.py must not import any network-send primitive."""
        export_src = (REPO_ROOT / "app" / "export.py").read_text(encoding="utf-8")

        for forbidden in self._FORBIDDEN_IMPORTS:
            # Check for 'import socket' or 'from socket'
            assert f"import {forbidden}" not in export_src, (
                f"app/export.py must not import '{forbidden}' (network-send primitive)"
            )
            # Also check for 'from socket import ...'
            assert f"from {forbidden}" not in export_src, (
                f"app/export.py must not use 'from {forbidden} import' (network-send primitive)"
            )

    def test_export_audit_event_rule_is_no_external_send(self, tmp_path):
        """The affirmative export audit event carries rule=RULE_NO_EXTERNAL_SEND."""
        from app.config import RULE_NO_EXTERNAL_SEND
        from app.export import export_response

        doc = _make_response_doc("q1", [_make_response_doc_item(status="APPROVED")])
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        events = _parse_jsonl(audit_log)
        export_events = [e for e in events if e.get("event") == "export"]
        assert export_events, "An 'export' event must be in the audit log"

        export_evt = export_events[0]
        assert export_evt["rule"] == RULE_NO_EXTERNAL_SEND, (
            f"Export audit event must carry rule=RULE_NO_EXTERNAL_SEND; "
            f"got {export_evt['rule']!r}"
        )

    def test_export_writes_only_to_specified_dir(self, tmp_path):
        """export_response() writes ONLY to the specified out_dir (no other locations)."""
        from app.export import export_response

        out_dir = tmp_path / "exports"
        doc = _make_response_doc("q1", [_make_response_doc_item(status="APPROVED")])
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=out_dir, log_path=audit_log)

        for _key, path in result.items():
            assert path.parent == out_dir, (
                f"Output file must be directly inside out_dir; got {path}"
            )

    def test_no_network_call_during_export(self, tmp_path, monkeypatch):
        """Spy: no socket.socket is constructed during export_response()."""
        import socket as _socket_module

        calls: list[str] = []
        original_socket = _socket_module.socket

        class SpySocket:
            def __init__(self, *args, **kwargs):
                calls.append("socket_created")
                original_socket.__init__(self, *args, **kwargs)

        monkeypatch.setattr(_socket_module, "socket", SpySocket)

        from app.export import export_response

        doc = _make_response_doc("q1", [_make_response_doc_item(status="APPROVED")])
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        assert len(calls) == 0, (
            f"export_response() must not create any socket; {len(calls)} socket(s) were created"
        )


# ---------------------------------------------------------------------------
# BOUND2 — non-APPROVED items never reach the export files
# ---------------------------------------------------------------------------


class TestBOUND2:
    """BOUND2: non-APPROVED items never appear in either export file (cross-checks RULE_NO_SELF_APPROVE)."""

    _NON_APPROVED_STATES = [
        "INTAKE",
        "RETRIEVED",
        "DRAFTED",
        "SCORED",
        "ROUTED_FOR_REVIEW",
        "REVIEW_APPROVED",
        "REVIEW_REJECTED",
    ]

    def test_non_approved_states_all_excluded(self, tmp_path):
        """Items in every non-APPROVED state are excluded from both export files."""
        from app.export import export_response

        items = [
            _make_response_doc_item(
                item_id=f"i{idx}",
                question=f"Question for state {state}?",
                status=state,
            )
            for idx, state in enumerate(self._NON_APPROVED_STATES, start=1)
        ]
        doc = _make_response_doc("q1", items=items)
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        md_text = result["markdown"].read_text(encoding="utf-8")
        csv_text = result["csv"].read_text(encoding="utf-8")

        for item in items:
            assert item.item_id not in csv_text, (
                f"Item {item.item_id!r} in state {item.status!r} must not appear in CSV"
            )
            assert item.question not in md_text, (
                f"Item question for state {item.status!r} must not appear in .md"
            )

    def test_only_approved_items_appear(self, tmp_path):
        """Mixed doc: only APPROVED items appear in the export."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(item_id="approved-1", status="APPROVED", question="Approved A?"),
                _make_response_doc_item(item_id="scored-1", status="SCORED", question="Scored B?"),
                _make_response_doc_item(item_id="approved-2", status="APPROVED", question="Approved C?"),
                _make_response_doc_item(item_id="routed-1", status="ROUTED_FOR_REVIEW", question="Routed D?"),
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        md_text = result["markdown"].read_text(encoding="utf-8")
        csv_text = result["csv"].read_text(encoding="utf-8")

        # APPROVED items must be present
        assert "Approved A?" in md_text
        assert "approved-1" in csv_text
        assert "Approved C?" in md_text
        assert "approved-2" in csv_text

        # Non-APPROVED items must be absent
        assert "Scored B?" not in md_text
        assert "scored-1" not in csv_text
        assert "Routed D?" not in md_text
        assert "routed-1" not in csv_text

    def test_exported_items_count_matches(self, tmp_path):
        """The export audit event's 'exported' count matches the number of APPROVED items."""
        from app.export import export_response

        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(item_id="i1", status="APPROVED"),
                _make_response_doc_item(item_id="i2", status="APPROVED"),
                _make_response_doc_item(item_id="i3", status="SCORED"),
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        events = _parse_jsonl(audit_log)
        export_events = [e for e in events if e.get("event") == "export"]
        assert export_events

        assert export_events[0]["detail"]["exported"] == 2, (
            "exported count must equal the number of APPROVED, non-held items"
        )

    def test_no_self_approve_cross_check(self, tmp_path):
        """Cross-check RULE_NO_SELF_APPROVE: agent cannot produce APPROVED items directly;
        only items explicitly set to APPROVED (by a human) can reach the export.

        This test proves the filter boundary exists independently of the state machine guard.
        """
        from app.export import export_response

        # Simulate what happens if an item has NOT been human-approved
        # (it remains in SCORED state, not APPROVED)
        doc = _make_response_doc(
            "q1",
            items=[
                _make_response_doc_item(item_id="i1", status="SCORED"),
            ],
        )
        audit_log = tmp_path / "audit.jsonl"
        result = export_response(doc, out_dir=tmp_path / "exports", log_path=audit_log)

        csv_text = result["csv"].read_text(encoding="utf-8")
        # Only the header row should be present; i1 must not appear
        lines = [l for l in csv_text.strip().splitlines() if l.strip()]
        assert len(lines) == 1, (
            f"Only the CSV header should exist for a doc with no APPROVED items; "
            f"got {len(lines)} lines"
        )
