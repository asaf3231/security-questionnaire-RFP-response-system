"""
app/export.py — local-disk Markdown + CSV response-document renderer.

Responsibility: render the response document (Markdown and CSV) for APPROVED items
only, gate sensitive items behind a human review check, and write files to local
disk — never to any external destination.

RULE_NO_EXTERNAL_SEND (chokepoint): this module has NO network/send capability.
  No socket, smtplib, urllib, http.client, requests, httpx, ftplib, or any send
  primitive is imported or used here. Export writes to local disk only.
  An affirmative audit event (rule=RULE_NO_EXTERNAL_SEND) is emitted on every export.

RULE_SENSITIVITY_GATE (chokepoint): items whose sensitivity tags include
  "internal" or "restricted" are held from export (SENSITIVITY_HOLD) unless
  the item carries review_approved=True (i.e. a human explicitly approved it).

Import-safe: no file created, no directory created, no network at import.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.audit import new_audit_event, write_audit
from app.config import (
    EXTERNAL_SEND_BLOCKED,
    REVIEW_BANNER,
    RULE_NO_EXTERNAL_SEND,
    RULE_SENSITIVITY_GATE,
    SENSITIVITY_HOLD,
)
from app.schema import ResponseDoc, ResponseDocItem

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sensitivity levels that require a human review before export
_RESTRICTED_SENSITIVITIES: frozenset[str] = frozenset({"internal", "restricted"})

# Default export directory (relative to the repo root); created lazily
_DEFAULT_EXPORT_DIR = Path(__file__).resolve().parent.parent / "exports"

# CSV column order (EXPORT1 spec)
_CSV_COLUMNS = ["item_id", "question", "status", "confidence_score", "queue", "citations"]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_markdown(items: list[ResponseDocItem]) -> str:
    """Render a list of ResponseDocItem objects as a Markdown response document.

    Each item becomes a numbered section with question, draft text, status,
    confidence score, queue, and citations.

    Parameters
    ----------
    items : list[ResponseDocItem]
        Items to render (caller decides which items to include).

    Returns
    -------
    str
        The Markdown document as a string.
    """
    lines: list[str] = []
    for idx, item in enumerate(items, start=1):
        lines.append(f"## {idx}. {item.question}")
        lines.append("")
        lines.append(item.draft_text)
        lines.append("")
        lines.append(f"**Status:** {item.status}")
        if item.confidence_score is not None:
            lines.append(f"**Confidence:** {item.confidence_score:.3f}")
        if item.queue:
            lines.append(f"**Reviewer queue:** {item.queue}")
        if item.citations:
            cids = ", ".join(c.chunk_id for c in item.citations)
            lines.append(f"**Citations:** {cids}")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def render_csv(items: list[ResponseDocItem]) -> str:
    """Render a list of ResponseDocItem objects as a CSV grid.

    Columns (EXPORT1 spec): item_id, question, status, confidence_score, queue, citations
    Citations are joined with ";" as the separator.

    Parameters
    ----------
    items : list[ResponseDocItem]
        Items to render.

    Returns
    -------
    str
        The CSV content as a string (UTF-8).
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for item in items:
        citations_str = ";".join(c.chunk_id for c in item.citations)
        writer.writerow([
            item.item_id,
            item.question,
            item.status,
            item.confidence_score if item.confidence_score is not None else "",
            item.queue or "",
            citations_str,
        ])
    return buf.getvalue()


def render_preview(doc: ResponseDoc) -> str:
    """Render ALL items in the document for human review.

    If ANY item has status != "APPROVED", the byte-exact REVIEW_BANNER is
    prepended as the first line (EXPORT3 / CLAUDE.md §7).

    Parameters
    ----------
    doc : ResponseDoc
        The full response document.

    Returns
    -------
    str
        The preview string, with REVIEW_BANNER prepended when applicable.
    """
    has_unapproved = any(item.status != "APPROVED" for item in doc.items)
    body = render_markdown(doc.items)
    if has_unapproved:
        return REVIEW_BANNER + "\n" + body
    return body


# ---------------------------------------------------------------------------
# Export entry point — the RULE_NO_EXTERNAL_SEND + RULE_SENSITIVITY_GATE chokepoint
# ---------------------------------------------------------------------------


def export_response(
    doc: ResponseDoc,
    *,
    out_dir: Path | None = None,
    log_path: Path | None = None,
) -> dict[str, Path]:
    """Export APPROVED items to local disk as Markdown + CSV.

    Governance enforced here (the single chokepoint for both rules):

    EXPORT1 / BOUND2: only items with status == "APPROVED" are considered for export.
    EXPORT2 / RULE_SENSITIVITY_GATE: items with sensitivities ∩ {internal, restricted}
      are held (SENSITIVITY_HOLD) unless review_approved is True.
    BOUND1 / RULE_NO_EXTERNAL_SEND: write to local disk only; emit an affirmative audit
      event with rule=RULE_NO_EXTERNAL_SEND confirming destination=local_disk.

    Parameters
    ----------
    doc : ResponseDoc
        The complete response document.
    out_dir : Path | None
        Directory for the output files; defaults to <repo>/exports/.
    log_path : Path | None
        Path to the audit JSONL file; forwarded to write_audit().

    Returns
    -------
    dict[str, Path]
        {"markdown": <path to .md file>, "csv": <path to .csv file>}
    """
    if out_dir is None:
        out_dir = _DEFAULT_EXPORT_DIR

    # Lazily create the export directory — never at import time.
    out_dir.mkdir(parents=True, exist_ok=True)

    qid = doc.questionnaire_id
    held_count = 0
    exportable: list[ResponseDocItem] = []

    for item in doc.items:
        # Gate 1: only APPROVED items can proceed (EXPORT1 / BOUND2)
        if item.status != "APPROVED":
            continue

        # Gate 2: sensitivity check (EXPORT2 / RULE_SENSITIVITY_GATE)
        blocked_sensitivities = _RESTRICTED_SENSITIVITIES & set(item.sensitivities)
        if blocked_sensitivities and not item.review_approved:
            # Hold this item — write a SENSITIVITY_HOLD audit event
            write_audit(
                new_audit_event(
                    questionnaire_id=qid,
                    item_id=item.item_id,
                    event="sensitivity_hold",
                    rule=RULE_SENSITIVITY_GATE,
                    detail={
                        "reason": SENSITIVITY_HOLD,
                        "sensitivities": list(blocked_sensitivities),
                        "review_approved": item.review_approved,
                    },
                ),
                log_path=log_path,
            )
            held_count += 1
            continue

        exportable.append(item)

    # Render and write — local disk only (RULE_NO_EXTERNAL_SEND)
    md_path = out_dir / f"{qid}.md"
    csv_path = out_dir / f"{qid}.csv"

    md_path.write_text(render_markdown(exportable), encoding="utf-8")
    csv_path.write_text(render_csv(exportable), encoding="utf-8")

    exported_count = len(exportable)

    # Affirmative local-only audit record (BOUND1 / RULE_NO_EXTERNAL_SEND)
    write_audit(
        new_audit_event(
            questionnaire_id=qid,
            item_id="*",
            event="export",
            rule=RULE_NO_EXTERNAL_SEND,
            detail={
                "reason": EXTERNAL_SEND_BLOCKED,
                "destination": "local_disk",
                "paths": [str(md_path), str(csv_path)],
                "exported": exported_count,
                "held": held_count,
            },
        ),
        log_path=log_path,
    )

    return {"markdown": md_path, "csv": csv_path}
