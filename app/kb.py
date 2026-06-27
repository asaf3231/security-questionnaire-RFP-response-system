"""
app/kb.py — KB + questionnaire + policy-tags load & validate layer.

Responsibility: load the synthetic data files by name (via pathlib relative to repo root),
validate every record against the schema, and return clean Python objects.
No retrieval ranking logic — that is Stage 2 (app/retrieval.py).

Enforces:
  KB1  — required fields present; sensitivity ∈ SENSITIVITY_TAGS; missing/bad field → ValueError
         chunk_id uniqueness across approved_answers + docs → ValueError on duplicate
  DATA1 — questionnaire + policy_tags validate; routing map references only REVIEWER_QUEUES
  KB2  — no data/* value is hardcoded here (all values come from the files, not from this code)
  RULE_NO_REAL_PII — only synthetic *.synthetic.* files are tracked; checked by LEAK2/LEAK3

Import-safe: no side effects at import — this module only defines functions.
The data files are read only when the loader functions are called, never at import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import SENSITIVITY_TAGS, REVIEWER_QUEUES
from app.schema import QuestionnaireItem, RetrievedChunk


# ---------------------------------------------------------------------------
# Path resolution — relative to the repo root (the directory containing app/)
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the absolute path to the repo root (parent of the app/ package)."""
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    return _repo_root() / "data"


# ---------------------------------------------------------------------------
# KB loader
# ---------------------------------------------------------------------------

def load_kb() -> list[RetrievedChunk]:
    """Load and validate the approved-answers KB from data/kb/approved_answers.synthetic.json.

    Returns a list of RetrievedChunk objects (all records, both approved and not).
    Callers should filter to .approved == True for retrieval (KB1).

    Raises ValueError on any record that fails validation (missing required field,
    invalid sensitivity, etc.) — never a KeyError or silent skip.
    """
    kb_path = _data_root() / "kb" / "approved_answers.synthetic.json"
    raw_records = _load_json(kb_path, context="KB approved_answers")

    if not isinstance(raw_records, list):
        raise ValueError(
            f"KB file must be a JSON array; got {type(raw_records).__name__} in {kb_path}"
        )

    chunks: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()

    for i, record in enumerate(raw_records):
        _validate_kb_record(record, index=i, path=kb_path)
        cid = record["chunk_id"]
        if cid in seen_chunk_ids:
            raise ValueError(
                f"Duplicate chunk_id '{cid}' found in KB (first occurrence in {kb_path})"
            )
        seen_chunk_ids.add(cid)
        chunk = RetrievedChunk(
            chunk_id=cid,
            question=record.get("question"),
            answer=record["answer"],
            source=record.get("source"),
            sensitivity=record["sensitivity"],
            topic_tags=record.get("topic_tags", []),
            approved=bool(record.get("approved", False)),
        )
        chunks.append(chunk)

    # Also load any doc chunks from data/kb/docs/
    docs_dir = _data_root() / "kb" / "docs"
    if docs_dir.is_dir():
        for doc_file in sorted(docs_dir.glob("*.synthetic.json")):
            doc_records = _load_json(doc_file, context=f"KB docs/{doc_file.name}")
            if not isinstance(doc_records, list):
                raise ValueError(
                    f"KB docs file must be a JSON array; got {type(doc_records).__name__} in {doc_file}"
                )
            for j, record in enumerate(doc_records):
                _validate_kb_record(record, index=j, path=doc_file)
                cid = record["chunk_id"]
                if cid in seen_chunk_ids:
                    raise ValueError(
                        f"Duplicate chunk_id '{cid}' found in KB (collision detected in {doc_file})"
                    )
                seen_chunk_ids.add(cid)
                chunk = RetrievedChunk(
                    chunk_id=cid,
                    question=record.get("question"),
                    answer=record["answer"],
                    source=record.get("source"),
                    sensitivity=record["sensitivity"],
                    topic_tags=record.get("topic_tags", []),
                    approved=bool(record.get("approved", False)),
                )
                chunks.append(chunk)

    return chunks


def _validate_kb_record(record: Any, *, index: int, path: Path) -> None:
    """Validate a single KB record dict. Raises ValueError (not KeyError) on any issue."""
    if not isinstance(record, dict):
        raise ValueError(
            f"KB record at index {index} in {path} must be a JSON object; "
            f"got {type(record).__name__}"
        )
    # Required fields — explicit ValueError, never KeyError
    for required_field in ("chunk_id", "answer", "sensitivity"):
        if required_field not in record:
            raise ValueError(
                f"KB record at index {index} in {path} is missing required field "
                f"'{required_field}'"
            )
        if not record[required_field]:
            raise ValueError(
                f"KB record at index {index} in {path} has empty required field "
                f"'{required_field}'"
            )
    # Sensitivity must be in the allowed set
    sensitivity = record["sensitivity"]
    if sensitivity not in SENSITIVITY_TAGS:
        raise ValueError(
            f"KB record '{record.get('chunk_id', f'index {index}')}' in {path} "
            f"has invalid sensitivity '{sensitivity}'; must be one of {SENSITIVITY_TAGS}"
        )


# ---------------------------------------------------------------------------
# Questionnaire loader
# ---------------------------------------------------------------------------

def load_questionnaire(path: Path | str) -> dict[str, Any]:
    """Load and validate a questionnaire file.

    Accepts a pathlib.Path or a string path.

    Returns a dict with keys:
      questionnaire_id: str
      items: list[QuestionnaireItem]

    Raises ValueError on missing required fields (not KeyError).
    """
    path = Path(path)
    raw = _load_json(path, context="questionnaire")

    if not isinstance(raw, dict):
        raise ValueError(
            f"Questionnaire file must be a JSON object; got {type(raw).__name__} in {path}"
        )

    if "questionnaire_id" not in raw:
        raise ValueError(f"Questionnaire in {path} is missing required field 'questionnaire_id'")

    if "items" not in raw:
        raise ValueError(f"Questionnaire in {path} is missing required field 'items'")

    if not isinstance(raw["items"], list):
        raise ValueError(
            f"Questionnaire 'items' in {path} must be a JSON array; "
            f"got {type(raw['items']).__name__}"
        )

    items: list[QuestionnaireItem] = []
    for i, item in enumerate(raw["items"]):
        if not isinstance(item, dict):
            raise ValueError(
                f"Questionnaire item at index {i} in {path} must be a JSON object"
            )
        for required_field in ("item_id", "question"):
            if required_field not in item:
                raise ValueError(
                    f"Questionnaire item at index {i} in {path} is missing "
                    f"required field '{required_field}'"
                )
        # Delegate further validation to the Pydantic model
        try:
            qi = QuestionnaireItem(
                item_id=item["item_id"],
                question=item["question"],
                topic_tags=item.get("topic_tags", []),
            )
        except Exception as exc:
            raise ValueError(
                f"Questionnaire item at index {i} in {path} failed validation: {exc}"
            ) from exc
        items.append(qi)

    return {
        "questionnaire_id": raw["questionnaire_id"],
        "items": items,
    }


# ---------------------------------------------------------------------------
# Policy tags loader
# ---------------------------------------------------------------------------

def load_policy_tags() -> dict[str, Any]:
    """Load and validate data/policy_tags.synthetic.json.

    Returns a dict with keys:
      sensitivity_tags: list[str]
      high_risk_tags: list[str]
      routing_map: dict[str, str]   # tag → queue

    Raises ValueError if the routing map references a queue not in REVIEWER_QUEUES.
    """
    path = _data_root() / "policy_tags.synthetic.json"
    raw = _load_json(path, context="policy_tags")

    if not isinstance(raw, dict):
        raise ValueError(
            f"policy_tags file must be a JSON object; got {type(raw).__name__} in {path}"
        )

    for required_key in ("sensitivity_tags", "high_risk_tags", "routing_map"):
        if required_key not in raw:
            raise ValueError(
                f"policy_tags in {path} is missing required key '{required_key}'"
            )

    routing_map = raw["routing_map"]
    if not isinstance(routing_map, dict):
        raise ValueError(
            f"policy_tags 'routing_map' in {path} must be a JSON object; "
            f"got {type(routing_map).__name__}"
        )

    # Validate all queues in the routing map are in REVIEWER_QUEUES
    for tag, queue in routing_map.items():
        if queue not in REVIEWER_QUEUES:
            raise ValueError(
                f"policy_tags routing_map entry '{tag}' → '{queue}' in {path} "
                f"references a queue not in REVIEWER_QUEUES {REVIEWER_QUEUES}"
            )

    return {
        "sensitivity_tags": raw["sensitivity_tags"],
        "high_risk_tags": raw["high_risk_tags"],
        "routing_map": routing_map,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path, *, context: str) -> Any:
    """Read and parse a JSON file; raise ValueError on any I/O or parse error."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ValueError(f"Required {context} file not found: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error in {context} file {path}: {exc}") from exc
