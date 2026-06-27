"""
app/eval/fixtures.py — Loader for labeled eval gold fixtures.

Responsibility: load and validate the labeled gold fixtures from fixtures/eval/.
Each fixture record has the shape:
  {
    "query": "<question text>",
    "relevant_chunk_ids": ["<chunk_id>", ...],
    "topic_tags": ["<tag>", ...]   # optional; passed to retrieve() as topic_tags filter
  }

Import-safe: no side effects at import — this module only defines functions.
Data is read only when load_eval_fixtures() is called, never at import.

RULE_NO_FABRICATED_METRIC: every Recall@K value is computed from these fixtures;
they are never fabricated or hardcoded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _fixtures_root() -> Path:
    """Return the absolute path to the fixtures/eval/ directory."""
    return Path(__file__).resolve().parent.parent.parent / "fixtures" / "eval"


def load_eval_fixtures() -> list[dict[str, Any]]:
    """Load all labeled gold fixtures from fixtures/eval/*.json.

    Returns a list of fixture dicts, each with keys:
      query: str
      relevant_chunk_ids: list[str]
      topic_tags: list[str]  (may be empty)

    Raises ValueError on any missing required field or malformed file.
    """
    root = _fixtures_root()
    if not root.is_dir():
        raise ValueError(f"Fixtures directory not found: {root}")

    fixtures: list[dict[str, Any]] = []
    json_files = sorted(root.glob("*.json"))
    if not json_files:
        raise ValueError(f"No .json fixture files found in {root}")

    for path in json_files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON parse error in fixture file {path}: {exc}") from exc

        if not isinstance(raw, list):
            raise ValueError(
                f"Fixture file must be a JSON array; got {type(raw).__name__} in {path}"
            )

        for i, record in enumerate(raw):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Fixture record at index {i} in {path} must be a JSON object"
                )
            for required_field in ("query", "relevant_chunk_ids"):
                if required_field not in record:
                    raise ValueError(
                        f"Fixture record at index {i} in {path} is missing "
                        f"required field '{required_field}'"
                    )
            if not isinstance(record["relevant_chunk_ids"], list):
                raise ValueError(
                    f"Fixture record at index {i} in {path}: "
                    f"'relevant_chunk_ids' must be a JSON array"
                )
            fixtures.append({
                "query": record["query"],
                "relevant_chunk_ids": record["relevant_chunk_ids"],
                "topic_tags": record.get("topic_tags", []),
            })

    return fixtures
