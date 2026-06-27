"""
app/audit.py — append-only JSONL audit logger for Comet.

Responsibility: create, redact, and persist AuditEvent records to a JSONL file,
one line per call. This is the spine of trust for every state transition and
tool call in the pipeline.

RULE_AUDIT_COMPLETE: every state transition and tool call emits exactly one event.
RULE_NO_SECRET / RULE_NO_REAL_PII: the redact() layer scrubs secrets and PII from
every event detail before it is written.

Import-safe: no file created, no directory created, no network activity at import.
All I/O is deferred to explicit function calls.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schema import AuditEvent

# ---------------------------------------------------------------------------
# Named regex constants for redact() — never inline magic patterns (CLAUDE §8)
# ---------------------------------------------------------------------------

# Anthropic secret-key token: sk-ant- followed by ≥ 20 alphanumeric/dash/underscore chars
_RE_SK_ANT = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")

# ANTHROPIC_API_KEY=<any non-whitespace value>
_RE_API_KEY_ASSIGNMENT = re.compile(r"ANTHROPIC_API_KEY=[^\s]+")

# Simple email address pattern
_RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# E.164 international phone numbers (+1234567890...) and long digit runs (≥ 7 consecutive digits)
_RE_PHONE = re.compile(r"\+\d{7,15}|\b\d{7,}\b")

# Replacement sentinels (named, not inline)
_REDACTED_SECRET = "[REDACTED-SECRET]"
_REDACTED_EMAIL = "[REDACTED-EMAIL]"
_REDACTED_PHONE = "[REDACTED-PHONE]"

# Default audit log location (relative to the repo root)
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "audit"
_DEFAULT_LOG_NAME = "audit.jsonl"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact(obj: Any) -> Any:
    """Recursively redact secrets and PII from a value before audit-log writing.

    Handles str, dict, list, and other types (returned unchanged).

    Patterns scrubbed (RULE_NO_SECRET / RULE_NO_REAL_PII):
      - Anthropic secret keys: sk-ant-<token>   → [REDACTED-SECRET]
      - ANTHROPIC_API_KEY=<value>                → [REDACTED-SECRET]
      - Email addresses                          → [REDACTED-EMAIL]
      - E.164 phones / long digit runs           → [REDACTED-PHONE]
    """
    if isinstance(obj, str):
        obj = _RE_SK_ANT.sub(_REDACTED_SECRET, obj)
        obj = _RE_API_KEY_ASSIGNMENT.sub(f"ANTHROPIC_API_KEY={_REDACTED_SECRET}", obj)
        obj = _RE_EMAIL.sub(_REDACTED_EMAIL, obj)
        obj = _RE_PHONE.sub(_REDACTED_PHONE, obj)
        return obj

    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [redact(item) for item in obj]

    return obj


def new_audit_event(
    *,
    questionnaire_id: str,
    item_id: str,
    event: str,
    from_state: str | None = None,
    to_state: str | None = None,
    rule: str | None = None,
    detail: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> AuditEvent:
    """Build a validated AuditEvent.

    Parameters
    ----------
    questionnaire_id : str
        The ID of the questionnaire this event belongs to.
    item_id : str
        The ID of the item this event belongs to.
    event : str
        Event descriptor (e.g. "state_transition", "tool_call", "export").
    from_state : str | None
        The state the item transitioned FROM (if applicable).
    to_state : str | None
        The state the item transitioned TO (if applicable).
    rule : str | None
        The RULE_* identifier that fired, or None.
    detail : dict | None
        Arbitrary structured data (will be redacted before writing).
    timestamp : str | None
        ISO-8601 timestamp; defaults to now (UTC). Inject for deterministic tests.

    Returns
    -------
    AuditEvent
        A validated Pydantic model ready for write_audit().
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    return AuditEvent(
        timestamp=timestamp,
        questionnaire_id=questionnaire_id,
        item_id=item_id,
        event=event,
        from_state=from_state,
        to_state=to_state,
        rule=rule,
        detail=detail or {},
    )


def write_audit(event: AuditEvent, *, log_path: Path | None = None) -> Path:
    """Append exactly one JSONL line for this AuditEvent to the audit log.

    The detail is redacted via redact() before serialisation.
    The audit/ directory is created lazily (never at import).
    The file is opened in append ("a") mode — the log is never truncated or rewritten.

    Parameters
    ----------
    event : AuditEvent
        The validated event to persist.
    log_path : Path | None
        Explicit path to the JSONL file; defaults to <repo>/audit/audit.jsonl.

    Returns
    -------
    Path
        The path to which the event was appended.
    """
    if log_path is None:
        log_path = _DEFAULT_LOG_DIR / _DEFAULT_LOG_NAME

    # Lazily create the parent directory — never at import time.
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Serialise: redact the detail dict (and any string fields) before writing.
    raw_dict = event.model_dump()
    raw_dict["detail"] = redact(raw_dict.get("detail", {}))

    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(raw_dict) + "\n")

    return log_path
