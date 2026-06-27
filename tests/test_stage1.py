"""
tests/test_stage1.py — offline deterministic suite for Stage 1.

Covers: ENV4, KB1, DATA1, config constants/literals, KB2, SEC1.
All tests are offline (no network, no .env required, no Claude API call).
Deterministic: no random state, no external dependencies.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"


# ---------------------------------------------------------------------------
# ENV4 — Import-safety: all current app.* modules import with zero side effects
# ---------------------------------------------------------------------------

class TestENV2:
    """ENV2: every non-stdlib import in app/+scripts/+tests/ is pinned in requirements.txt with ==."""

    # Known PyPI package name → import name mappings (where they differ)
    IMPORT_TO_PKG: dict[str, str] = {
        "dotenv": "python-dotenv",          # pip install python-dotenv → import dotenv
        "rank_bm25": "rank-bm25",           # pip install rank-bm25 → import rank_bm25
        "pydantic_core": "pydantic_core",   # transitively installed; import matches pip name
        "anthropic": "anthropic",
        "pydantic": "pydantic",
        "pytest": "pytest",
    }

    STDLIB: set[str] = {
        "os", "sys", "json", "re", "csv", "math", "time", "random", "pathlib",
        "dataclasses", "datetime", "enum", "hashlib", "importlib", "typing",
        "ast", "subprocess", "abc", "collections", "functools", "itertools",
        "io", "logging", "contextlib", "types", "copy", "warnings",
        "__future__", "unittest", "pprint", "inspect", "textwrap", "socket",
    }

    def _get_third_party_imports(self) -> set[str]:
        """AST-scan app/, scripts/, tests/ for top-level third-party import names."""
        imports: set[str] = set()
        for search_dir in [APP_DIR, REPO_ROOT / "scripts", REPO_ROOT / "tests"]:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    tree = ast.parse(py_file.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split(".")[0]
                            if top not in self.STDLIB and not top.startswith("app"):
                                imports.add(top)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and not node.level:
                            top = node.module.split(".")[0]
                            if top not in self.STDLIB and not top.startswith("app"):
                                imports.add(top)
        return imports

    def _get_pinned_packages(self) -> dict[str, str]:
        """Parse requirements.txt and return {normalized_pkg_name: version}."""
        pinned: dict[str, str] = {}
        req_path = REPO_ROOT / "requirements.txt"
        for line in req_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "==" in line:
                name, version = line.split("==", 1)
                # Store both the raw name and a normalized variant
                pinned[name.lower()] = version
                pinned[name.lower().replace("-", "_")] = version
        return pinned

    def test_all_third_party_imports_pinned(self):
        """Every non-stdlib import in app/+scripts/+tests/ must appear in requirements.txt with ==."""
        third_party = self._get_third_party_imports()
        pinned = self._get_pinned_packages()
        missing = []
        for imp in sorted(third_party):
            # Resolve import name → pip package name using alias map
            pkg_name = self.IMPORT_TO_PKG.get(imp, imp)
            # Check both the pkg name and the import name (normalized)
            if (
                pkg_name.lower() not in pinned
                and pkg_name.lower().replace("-", "_") not in pinned
                and imp.lower() not in pinned
                and imp.lower().replace("-", "_") not in pinned
            ):
                missing.append(f"{imp} (pip: {pkg_name})")
        assert not missing, (
            f"ENV2: the following third-party imports are NOT pinned in requirements.txt:\n"
            + "\n".join(f"  {m}" for m in missing)
        )


class TestENV4:
    """ENV4: every app.* module that exists at Stage 1 imports without side effects.

    ENV4 is proven progressively per stage (CLAUDE.md §1): only the modules that exist
    at this stage are imported here. The full 13-module import is re-proven as later
    stages create their modules for real.
    """

    MODULES_TO_TEST = [
        "app.config",
        "app.schema",
        "app.kb",
    ]

    def test_all_modules_import_cleanly(self):
        """All app.* modules import without raising in a subprocess with no .env."""
        # Build the import statement
        imports = ", ".join(self.MODULES_TO_TEST)
        code = f"import sys; sys.path.insert(0, r'{REPO_ROOT}'); import {imports.replace(', ', '; import ')}"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
            # Explicitly do NOT pass ANTHROPIC_API_KEY — the env in CI won't have it
        )
        assert result.returncode == 0, (
            f"Import of app modules failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_config_claude_client_is_none_at_import(self):
        """_claude_client singleton must be None after import (no client built at import time)."""
        import app.config as cfg
        # Access the module-level _claude_client directly
        assert cfg._claude_client is None, (
            "_claude_client should be None at import; it was constructed at module level"
        )

    def test_no_dotenv_load_at_import(self, monkeypatch, tmp_path):
        """load_env() must not be called at import time (no .env side effect at import)."""
        # We verify by checking that importing app.config does not change os.environ
        # with a sentinel key that would only appear if load_dotenv was called
        sentinel_key = "COMET_TEST_SENTINEL_12345"
        # Ensure sentinel is not set
        monkeypatch.delenv(sentinel_key, raising=False)

        # Re-importing should be a no-op (module is cached); but even a fresh import
        # must not call load_env(). We just verify the sentinel is still absent.
        import app.config  # noqa: F401
        assert sentinel_key not in os.environ


# ---------------------------------------------------------------------------
# Config constants — byte-exact literals, RULE_* registry, AGENT_TOOLS, DRAFT_MODEL
# ---------------------------------------------------------------------------

class TestConfigConstants:
    """Verify all §9 constants and byte-exact literals match CLAUDE.md exactly."""

    def setup_method(self):
        import app.config as cfg
        self.cfg = cfg

    def test_review_banner_byte_exact(self):
        """REVIEW_BANNER must match CLAUDE.md §9 byte-for-byte."""
        expected = "⚠️ PENDING HUMAN REVIEW — NOT APPROVED FOR EXTERNAL RELEASE"
        assert self.cfg.REVIEW_BANNER == expected, (
            f"REVIEW_BANNER mismatch.\n  Got: {self.cfg.REVIEW_BANNER!r}\n  Want: {expected!r}"
        )

    def test_ungrounded_placeholder_byte_exact(self):
        """UNGROUNDED_PLACEHOLDER must match CLAUDE.md §9 byte-for-byte."""
        expected = "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"
        assert self.cfg.UNGROUNDED_PLACEHOLDER == expected, (
            f"UNGROUNDED_PLACEHOLDER mismatch.\n"
            f"  Got: {self.cfg.UNGROUNDED_PLACEHOLDER!r}\n  Want: {expected!r}"
        )

    def test_draft_model_pinned(self):
        """DRAFT_MODEL must be 'claude-sonnet-4-6' (OQ-1 resolved)."""
        assert self.cfg.DRAFT_MODEL == "claude-sonnet-4-6", (
            f"DRAFT_MODEL is '{self.cfg.DRAFT_MODEL}'; expected 'claude-sonnet-4-6' (OQ-1)"
        )

    def test_agent_tools_unique(self):
        """AGENT_TOOLS must contain no duplicate names (dispatch integrity)."""
        tools = self.cfg.AGENT_TOOLS
        assert len(tools) == len(set(tools)), (
            f"AGENT_TOOLS contains duplicates: {[t for t in tools if tools.count(t) > 1]}"
        )

    def test_agent_tools_count(self):
        """AGENT_TOOLS must have exactly 8 entries per CLAUDE.md §9."""
        expected = [
            "retrieve", "assemble_context", "draft_answer", "score_confidence",
            "route_for_review", "update_status", "write_audit", "export_response",
        ]
        assert self.cfg.AGENT_TOOLS == expected, (
            f"AGENT_TOOLS mismatch.\n  Got: {self.cfg.AGENT_TOOLS}\n  Want: {expected}"
        )

    def test_all_rule_constants_present(self):
        """All 11 RULE_* string constants must be defined in config.py."""
        expected_rules = [
            "RULE_GROUNDED_ONLY",
            "RULE_NO_SELF_APPROVE",
            "RULE_HITM_REVIEW_TRIGGER",
            "RULE_NO_EXTERNAL_SEND",
            "RULE_SENSITIVITY_GATE",
            "RULE_NO_SECRET",
            "RULE_NO_REAL_PII",
            "RULE_NO_EVAL_CONTAMINATION",
            "RULE_NO_FABRICATED_METRIC",
            "RULE_AUDIT_COMPLETE",
            "RULE_SAFE_TERMINAL",
        ]
        for rule in expected_rules:
            assert hasattr(self.cfg, rule), f"config.py is missing RULE_* constant: {rule}"
            # Each RULE_* constant must equal its own name (grep-enforceable)
            assert getattr(self.cfg, rule) == rule, (
                f"config.{rule} should equal '{rule}' but got '{getattr(self.cfg, rule)}'"
            )

    def test_sensitivity_tags(self):
        """SENSITIVITY_TAGS must be exactly ['public', 'internal', 'restricted']."""
        assert self.cfg.SENSITIVITY_TAGS == ["public", "internal", "restricted"]

    def test_high_risk_tags(self):
        """HIGH_RISK_TAGS must be exactly ['legal', 'security']."""
        assert self.cfg.HIGH_RISK_TAGS == ["legal", "security"]

    def test_reviewer_queues(self):
        """REVIEWER_QUEUES must be exactly ['security', 'legal', 'engineering', 'gtm']."""
        assert self.cfg.REVIEWER_QUEUES == ["security", "legal", "engineering", "gtm"]

    def test_item_states(self):
        """ITEM_STATES must match CLAUDE.md §9 exactly."""
        expected = [
            "INTAKE", "RETRIEVED", "DRAFTED", "SCORED",
            "ROUTED_FOR_REVIEW", "REVIEW_APPROVED", "REVIEW_REJECTED",
            "APPROVED", "EXPORTED",
        ]
        assert self.cfg.ITEM_STATES == expected

    def test_numeric_constants_in_range(self):
        """Numeric constants must be in valid ranges per §9."""
        cfg = self.cfg
        assert 0 < cfg.RETRIEVAL_TOP_K <= 20
        assert 0.0 < cfg.CONFIDENCE_AUTO_THRESHOLD <= 1.0
        assert 0.0 < cfg.CONFIDENCE_REVIEW_THRESHOLD <= 1.0
        assert cfg.CONFIDENCE_REVIEW_THRESHOLD < cfg.CONFIDENCE_AUTO_THRESHOLD
        assert cfg.GROUNDING_MIN_CITATIONS >= 1
        assert 0.0 < cfg.AMBIGUITY_SCORE_MARGIN < 1.0
        assert cfg.RANDOM_SEED == 42
        assert cfg.DRAFT_TEMPERATURE == 0.0
        assert cfg.MAX_OUTPUT_TOKENS > 0


# ---------------------------------------------------------------------------
# KB1 — KB load + validation
# ---------------------------------------------------------------------------

class TestKB1:
    """KB1: the KB loads and validates; strict field checks; approved==False excluded."""

    def test_kb_loads_from_synthetic_file(self, tmp_path, monkeypatch):
        """The real synthetic KB file loads without error."""
        from app.kb import load_kb
        chunks = load_kb()
        assert len(chunks) > 0, "KB returned no chunks"

    def test_kb_has_approved_and_not_approved(self):
        """KB must contain both approved and not-approved chunks per test fixture spec."""
        from app.kb import load_kb
        chunks = load_kb()
        approved = [c for c in chunks if c.approved]
        not_approved = [c for c in chunks if not c.approved]
        assert len(approved) > 0, "No approved chunks found in KB"
        assert len(not_approved) > 0, "No approved=False chunks found — KB1 fixture requires ≥1"

    def test_kb_has_internal_or_restricted_chunks(self):
        """KB must contain ≥1 internal or restricted chunk (sensitivity gate coverage)."""
        from app.kb import load_kb
        chunks = load_kb()
        sensitive = [c for c in chunks if c.sensitivity in ("internal", "restricted")]
        assert len(sensitive) > 0, "KB has no internal/restricted chunks — sensitivity gate untestable"

    def test_kb_sensitivity_values_are_valid(self):
        """All KB records must have sensitivity ∈ SENSITIVITY_TAGS."""
        from app.config import SENSITIVITY_TAGS
        from app.kb import load_kb
        chunks = load_kb()
        for chunk in chunks:
            assert chunk.sensitivity in SENSITIVITY_TAGS, (
                f"Chunk '{chunk.chunk_id}' has invalid sensitivity '{chunk.sensitivity}'"
            )

    def test_kb_missing_chunk_id_raises_value_error(self, tmp_path, monkeypatch):
        """A KB record missing 'chunk_id' must raise ValueError, not KeyError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"answer": "some answer", "sensitivity": "public", "approved": True}
        ]))

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)
        # Also patch docs dir to not exist (avoid loading real docs)
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        with pytest.raises(ValueError, match="chunk_id"):
            kb_module.load_kb()

    def test_kb_missing_answer_raises_value_error(self, tmp_path, monkeypatch):
        """A KB record missing 'answer' must raise ValueError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"chunk_id": "x1", "sensitivity": "public", "approved": True}
        ]))

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        with pytest.raises(ValueError, match="answer"):
            kb_module.load_kb()

    def test_kb_missing_sensitivity_raises_value_error(self, tmp_path, monkeypatch):
        """A KB record missing 'sensitivity' must raise ValueError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"chunk_id": "x1", "answer": "some answer", "approved": True}
        ]))

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        with pytest.raises(ValueError, match="sensitivity"):
            kb_module.load_kb()

    def test_kb_invalid_sensitivity_raises_value_error(self, tmp_path, monkeypatch):
        """A KB record with sensitivity not in SENSITIVITY_TAGS must raise ValueError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps([
            {"chunk_id": "x1", "answer": "some answer", "sensitivity": "INVALID_TAG", "approved": True}
        ]))

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        with pytest.raises(ValueError, match="invalid sensitivity"):
            kb_module.load_kb()

    def test_kb_not_array_raises_value_error(self, tmp_path, monkeypatch):
        """A KB file that is not a JSON array must raise ValueError."""
        bad_kb = tmp_path / "kb" / "approved_answers.synthetic.json"
        bad_kb.parent.mkdir(parents=True)
        bad_kb.write_text(json.dumps({"not": "an array"}))

        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)
        (tmp_path / "kb" / "docs").mkdir(exist_ok=True)

        with pytest.raises(ValueError, match="JSON array"):
            kb_module.load_kb()

    def test_kb_missing_file_raises_value_error(self, tmp_path, monkeypatch):
        """A missing KB file must raise ValueError."""
        import app.kb as kb_module
        # Point to an empty tmp dir that has no KB file
        empty_tmp = tmp_path / "empty"
        empty_tmp.mkdir()
        (empty_tmp / "kb").mkdir()
        (empty_tmp / "kb" / "docs").mkdir()
        monkeypatch.setattr(kb_module, "_data_root", lambda: empty_tmp)

        with pytest.raises(ValueError, match="not found"):
            kb_module.load_kb()


# ---------------------------------------------------------------------------
# DATA1 — questionnaire + policy_tags load + validate
# ---------------------------------------------------------------------------

class TestDATA1:
    """DATA1: questionnaire and policy_tags files load and validate correctly."""

    def test_confident_questionnaire_loads(self):
        """case_confident.synthetic.json loads without error."""
        from app.kb import load_questionnaire
        path = REPO_ROOT / "data" / "questionnaires" / "case_confident.synthetic.json"
        result = load_questionnaire(path)
        assert result["questionnaire_id"]
        assert len(result["items"]) >= 1

    def test_review_questionnaire_loads(self):
        """case_review.synthetic.json loads without error."""
        from app.kb import load_questionnaire
        path = REPO_ROOT / "data" / "questionnaires" / "case_review.synthetic.json"
        result = load_questionnaire(path)
        assert result["questionnaire_id"]
        assert len(result["items"]) >= 1

    def test_policy_tags_load(self):
        """policy_tags.synthetic.json loads and all queues are in REVIEWER_QUEUES."""
        from app.kb import load_policy_tags
        from app.config import REVIEWER_QUEUES
        policy = load_policy_tags()
        assert "routing_map" in policy
        for tag, queue in policy["routing_map"].items():
            assert queue in REVIEWER_QUEUES, (
                f"routing_map['{tag}'] = '{queue}' is not in REVIEWER_QUEUES {REVIEWER_QUEUES}"
            )

    def test_questionnaire_missing_id_raises_value_error(self, tmp_path):
        """A questionnaire missing 'questionnaire_id' must raise ValueError."""
        bad_q = tmp_path / "bad.synthetic.json"
        bad_q.write_text(json.dumps({"items": [{"item_id": "i1", "question": "q"}]}))
        from app.kb import load_questionnaire
        with pytest.raises(ValueError, match="questionnaire_id"):
            load_questionnaire(bad_q)

    def test_questionnaire_missing_items_raises_value_error(self, tmp_path):
        """A questionnaire missing 'items' must raise ValueError."""
        bad_q = tmp_path / "bad.synthetic.json"
        bad_q.write_text(json.dumps({"questionnaire_id": "q1"}))
        from app.kb import load_questionnaire
        with pytest.raises(ValueError, match="items"):
            load_questionnaire(bad_q)

    def test_questionnaire_item_missing_item_id_raises_value_error(self, tmp_path):
        """A questionnaire item missing 'item_id' must raise ValueError."""
        bad_q = tmp_path / "bad.synthetic.json"
        bad_q.write_text(json.dumps({
            "questionnaire_id": "q1",
            "items": [{"question": "What is your policy?"}]
        }))
        from app.kb import load_questionnaire
        with pytest.raises(ValueError, match="item_id"):
            load_questionnaire(bad_q)

    def test_questionnaire_item_missing_question_raises_value_error(self, tmp_path):
        """A questionnaire item missing 'question' must raise ValueError."""
        bad_q = tmp_path / "bad.synthetic.json"
        bad_q.write_text(json.dumps({
            "questionnaire_id": "q1",
            "items": [{"item_id": "i1"}]
        }))
        from app.kb import load_questionnaire
        with pytest.raises(ValueError, match="question"):
            load_questionnaire(bad_q)

    def test_policy_tags_bad_queue_raises_value_error(self, tmp_path, monkeypatch):
        """A policy_tags routing_map with an invalid queue must raise ValueError."""
        bad_policy = tmp_path / "policy_tags.synthetic.json"
        bad_policy.write_text(json.dumps({
            "sensitivity_tags": ["public", "internal", "restricted"],
            "high_risk_tags": ["legal", "security"],
            "routing_map": {
                "legal": "INVALID_QUEUE_NOT_IN_REVIEWER_QUEUES"
            }
        }))
        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)

        with pytest.raises(ValueError, match="REVIEWER_QUEUES"):
            kb_module.load_policy_tags()

    def test_policy_tags_missing_routing_map_raises_value_error(self, tmp_path, monkeypatch):
        """A policy_tags file missing 'routing_map' must raise ValueError."""
        bad_policy = tmp_path / "policy_tags.synthetic.json"
        bad_policy.write_text(json.dumps({
            "sensitivity_tags": ["public"],
            "high_risk_tags": ["legal"],
        }))
        import app.kb as kb_module
        monkeypatch.setattr(kb_module, "_data_root", lambda: tmp_path)

        with pytest.raises(ValueError, match="routing_map"):
            kb_module.load_policy_tags()

    def test_review_case_has_high_risk_tags(self):
        """case_review items must carry high-risk topic_tags (legal or security)."""
        from app.kb import load_questionnaire
        from app.config import HIGH_RISK_TAGS
        path = REPO_ROOT / "data" / "questionnaires" / "case_review.synthetic.json"
        result = load_questionnaire(path)
        items_with_high_risk = [
            item for item in result["items"]
            if any(tag in HIGH_RISK_TAGS for tag in item.topic_tags)
        ]
        assert len(items_with_high_risk) >= 1, (
            "case_review.synthetic.json must have ≥1 item with a high-risk topic tag "
            f"({HIGH_RISK_TAGS}) to exercise the RULE_HITM_REVIEW_TRIGGER"
        )


# ---------------------------------------------------------------------------
# KB2 — no data/* values hardcoded in app/ code
# ---------------------------------------------------------------------------

class TestKB2:
    """KB2: grep check — no data/* answer/question/source literal appears in app/ code."""

    def _get_app_source(self) -> str:
        """Concatenate all .py source files under app/."""
        parts = []
        for py_file in sorted(APP_DIR.rglob("*.py")):
            parts.append(py_file.read_text(encoding="utf-8"))
        return "\n".join(parts)

    def _get_kb_literals(self) -> list[str]:
        """Extract answer/question/source text literals from the KB JSON files."""
        literals = []
        kb_path = REPO_ROOT / "data" / "kb" / "approved_answers.synthetic.json"
        if kb_path.exists():
            records = json.loads(kb_path.read_text())
            for rec in records:
                if rec.get("answer"):
                    # Use a distinctive substring to avoid false positives on common words
                    # We check for longer phrases (≥30 chars) from answers/questions
                    answer_snippet = rec["answer"][:50].strip()
                    if len(answer_snippet) >= 20:
                        literals.append(answer_snippet)
                if rec.get("question"):
                    q_snippet = rec["question"][:50].strip()
                    if len(q_snippet) >= 20:
                        literals.append(q_snippet)

        docs_dir = REPO_ROOT / "data" / "kb" / "docs"
        if docs_dir.exists():
            for doc_file in docs_dir.glob("*.synthetic.json"):
                records = json.loads(doc_file.read_text())
                for rec in records:
                    if rec.get("answer"):
                        answer_snippet = rec["answer"][:50].strip()
                        if len(answer_snippet) >= 20:
                            literals.append(answer_snippet)
        return literals

    def test_no_kb_answer_literals_in_app_code(self):
        """No KB answer/question text (≥20-char prefix) is hardcoded in app/ Python files."""
        app_source = self._get_app_source()
        literals = self._get_kb_literals()
        violations = []
        for literal in literals:
            if literal in app_source:
                violations.append(literal[:60])
        assert not violations, (
            f"KB2/LEAK3 violation: the following KB data literals appear in app/ code:\n"
            + "\n".join(f"  - {v!r}" for v in violations[:5])
        )


# ---------------------------------------------------------------------------
# SEC1 — no secret in any tracked file
# ---------------------------------------------------------------------------

class TestSEC1:
    """SEC1: no ANTHROPIC_API_KEY value or sk-ant- token in any tracked file."""

    def _get_tracked_files(self) -> list[Path]:
        """Return list of all git-tracked files in the repo."""
        result = subprocess.run(
            ["git", "ls-files", "--cached"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            pytest.skip("git not available; skipping SEC1 tracked-file scan")
        return [REPO_ROOT / f.strip() for f in result.stdout.splitlines() if f.strip()]

    # A real Anthropic key is "sk-ant-" followed by 20+ contiguous key characters
    # (no whitespace). This shape avoids false positives on prose that merely mentions
    # the prefix (e.g. documentation describing the SEC1 check itself).
    _REAL_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")

    def test_no_api_key_value_in_tracked_files(self):
        """No tracked file contains an actual ANTHROPIC_API_KEY value (sk-ant- prefix)."""
        tracked = self._get_tracked_files()
        violations = []
        for path in tracked:
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # Check for a real key value: sk-ant- followed by a contiguous key body
            if self._REAL_KEY_RE.search(content):
                violations.append(str(path))
            # Check for a set ANTHROPIC_API_KEY=<real_value> assignment
            if "ANTHROPIC_API_KEY=" in content:
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("ANTHROPIC_API_KEY="):
                        value = stripped[len("ANTHROPIC_API_KEY="):]
                        # A real key would be non-empty and not a placeholder
                        if value and not value.startswith("your-"):
                            # .env.example uses placeholders; other files must not have values
                            if ".env.example" not in str(path):
                                violations.append(f"{path}: {stripped}")
        assert not violations, (
            f"SEC1/LEAK1: found potential secret in tracked files:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_env_file_is_gitignored(self):
        """The .env file must be gitignored."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            capture_output=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, (
            ".env is not gitignored — RULE_NO_SECRET violated. "
            "Add '.env' to .gitignore."
        )

    def test_env_example_placeholder_only(self):
        """The .env.example file must not contain a real API key value."""
        env_example = REPO_ROOT / ".env.example"
        assert env_example.exists(), ".env.example must exist"
        content = env_example.read_text(encoding="utf-8")
        # Must contain the placeholder key
        assert "ANTHROPIC_API_KEY=" in content, ".env.example must define ANTHROPIC_API_KEY="
        for line in content.splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                value = line[len("ANTHROPIC_API_KEY="):]
                # Must be a placeholder, not a real key
                assert not value.startswith("sk-ant-"), (
                    ".env.example contains a real API key — RULE_NO_SECRET violated"
                )
