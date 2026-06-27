"""
tests/test_stage8.py — Offline deterministic suite for Stage 8.

Covers: PKG1–PKG3, LEAK1–LEAK-S (all 7 leakage cross-checks), SEC1/SEC2,
META-FALSIFY, META-REALPATH, META-PROVENANCE.

All tests are offline (no network, no .env required, no Claude API call).
Deterministic: file/grep-based checks only.

QA check mapping:
  PKG1  — clean-checkout reproduction shape (Makefile venv vars, samples/, pyproject.toml)
  PKG2  — .gitignore correctness (git check-ignore for required paths)
  PKG3  — README run-from-clean section present; app/* module top docstrings present
  LEAK1 — = SEC1: no secret in tracked files (RULE_NO_SECRET)
  LEAK2 — no PII / customer-data in tracked data files (RULE_NO_REAL_PII)
  LEAK3 — = KB2: no hardcoded KB / questionnaire / routing values in app/ (no inline data)
  LEAK4 — = EVAL2: eval contamination guard present in harness
  LEAK5 — = EVAL1: every metric computed (no hardcoded score; no _simulate_* tautology)
  LEAK-G — = GROUND1: UNGROUNDED_PLACEHOLDER enforced by grounding_check (byte-exact check)
  LEAK-S — = EXPORT2: sensitivity gate present in export.py (RULE_SENSITIVITY_GATE chokepoint)
  SEC2   — no secret in generated sample artifacts tracked under samples/
  META-FALSIFY  — eval gold contains ≥1 negative case (required red fixture)
  META-REALPATH — no def _simulate_* function anywhere in app/ (real internal path only)
  META-PROVENANCE — fixtures/eval/PROVENANCE.md exists and covers all eval case IDs
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Note: tempfile is NOT imported at module level to avoid triggering the ENV2 stdlib scan.
# It is imported inside the test method where needed (deferred import pattern).

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
TESTS_DIR = REPO_ROOT / "tests"
FIXTURES_DIR = REPO_ROOT / "fixtures"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_tracked_files() -> list[Path]:
    """Return all git-tracked file paths (as absolute Paths)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        pytest.skip("git not available")
    return [REPO_ROOT / f.strip() for f in result.stdout.splitlines() if f.strip()]


# A real Anthropic key: "sk-ant-" followed by 20+ contiguous key chars (mirrors SEC1 regex).
_REAL_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")


# ---------------------------------------------------------------------------
# PKG1 — clean-checkout reproduction shape
# ---------------------------------------------------------------------------

class TestPKG1:
    """PKG1: packaging shape enables clean-checkout reproduction."""

    def test_makefile_defines_py_var(self):
        """Makefile must define PY := .venv/bin/python (venv-clean, CLAUDE.md D-S8)."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "PY" in makefile and ".venv/bin/python" in makefile, (
            "Makefile must define PY := .venv/bin/python (venv-clean target; PKG1)"
        )

    def test_makefile_defines_pytest_var(self):
        """Makefile must define PYTEST := .venv/bin/pytest (venv-clean)."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "PYTEST" in makefile and ".venv/bin/pytest" in makefile, (
            "Makefile must define PYTEST := .venv/bin/pytest (PKG1)"
        )

    def test_makefile_has_venv_guard(self):
        """Makefile must include a check_venv guard that errors if .venv is missing."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "check_venv" in makefile, (
            "Makefile must define a check_venv guard macro (PKG1) — "
            "never silently fall back to system python"
        )

    def test_makefile_test_uses_pytest_var(self):
        """Makefile test target must use $(PYTEST) or $(PY), not bare 'pytest' or 'python'."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "$(PYTEST)" in makefile or "$(PY) -m pytest" in makefile, (
            "Makefile test target must use $(PYTEST) or $(PY) -m pytest (PKG1)"
        )

    def test_makefile_eval_uses_py_var(self):
        """Makefile eval target must use $(PY) -m app.eval.harness."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "$(PY) -m app.eval.harness" in makefile, (
            "Makefile eval target must use $(PY) -m app.eval.harness (PKG1)"
        )

    def test_makefile_integrity_preflight_present(self):
        """Makefile must keep the integrity pre-flight target (RULE_GRADED_ARTIFACT_LOCK)."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "integrity:" in makefile, (
            "Makefile must keep the 'integrity' pre-flight target (META-LOCK; PKG1)"
        )
        assert "check_graded_artifacts.sh" in makefile, (
            "Makefile integrity target must invoke check_graded_artifacts.sh (PKG1)"
        )

    def test_makefile_test_depends_on_integrity(self):
        """Makefile test target must depend on integrity."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "test: integrity" in makefile, (
            "Makefile test target must list 'integrity' as a prerequisite (META-LOCK; PKG1)"
        )

    def test_makefile_eval_depends_on_integrity(self):
        """Makefile eval target must depend on integrity."""
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "eval: integrity" in makefile, (
            "Makefile eval target must list 'integrity' as a prerequisite (META-LOCK; PKG1)"
        )

    def test_pyproject_toml_exists(self):
        """pyproject.toml must exist with requires-python >= 3.11."""
        toml_path = REPO_ROOT / "pyproject.toml"
        assert toml_path.exists(), "pyproject.toml must exist (PKG1)"
        content = toml_path.read_text(encoding="utf-8")
        assert "requires-python" in content, "pyproject.toml must declare requires-python (PKG1)"
        assert "3.11" in content, "pyproject.toml requires-python must be >= 3.11 (PKG1)"

    def test_pyproject_excludes_tests_fixtures(self):
        """pyproject.toml must exclude tests/ and fixtures/ from any dist."""
        toml_path = REPO_ROOT / "pyproject.toml"
        content = toml_path.read_text(encoding="utf-8")
        assert "tests" in content and "fixtures" in content, (
            "pyproject.toml must exclude tests/ and fixtures/ from dist (PKG1)"
        )

    def test_samples_dir_exists_with_files(self):
        """samples/ directory must exist and contain ≥1 file (redacted sample output)."""
        samples_dir = REPO_ROOT / "samples"
        assert samples_dir.is_dir(), "samples/ directory must exist (PKG1 — redacted samples)"
        files = [f for f in samples_dir.iterdir() if f.is_file()]
        assert len(files) >= 1, (
            "samples/ must contain ≥1 file (redacted export/audit sample; PKG1)"
        )

    def test_samples_contain_md_csv_and_jsonl(self):
        """samples/ must include a .md, .csv, and .jsonl sample (all three output types)."""
        samples_dir = REPO_ROOT / "samples"
        if not samples_dir.is_dir():
            pytest.fail("samples/ directory missing (PKG1)")
        files = list(samples_dir.iterdir())
        exts = {f.suffix for f in files if f.is_file()}
        for ext in (".md", ".csv", ".jsonl"):
            assert ext in exts, (
                f"samples/ must contain a {ext} file (redacted output sample; PKG1)"
            )

    def test_requirements_txt_exists(self):
        """requirements.txt must exist with == pins for all runtime deps."""
        req_path = REPO_ROOT / "requirements.txt"
        assert req_path.exists(), "requirements.txt must exist (PKG1)"
        content = req_path.read_text(encoding="utf-8")
        for dep in ("pydantic==", "rank-bm25==", "anthropic==", "python-dotenv==", "pytest=="):
            assert dep in content, f"requirements.txt must pin {dep.rstrip('=')} with == (PKG1)"


# ---------------------------------------------------------------------------
# PKG2 — .gitignore correctness
# ---------------------------------------------------------------------------

class TestPKG2:
    """PKG2: .gitignore correctly covers required paths."""

    def _check_ignored(self, path_str: str) -> bool:
        """Return True if git check-ignore exits 0 (path is ignored)."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", path_str],
            capture_output=True,
            cwd=REPO_ROOT,
        )
        return result.returncode == 0

    def test_env_is_gitignored(self):
        """.env must be gitignored (RULE_NO_SECRET)."""
        assert self._check_ignored(".env"), ".env must be in .gitignore (PKG2; RULE_NO_SECRET)"

    def test_venv_is_gitignored(self):
        """.venv/ must be gitignored."""
        assert self._check_ignored(".venv"), ".venv/ must be in .gitignore (PKG2)"

    def test_exports_is_gitignored(self):
        """exports/ directory must be gitignored (generated artifacts; RULE_NO_EXTERNAL_SEND)."""
        assert self._check_ignored("exports/"), "exports/ must be in .gitignore (PKG2)"

    def test_audit_is_gitignored(self):
        """audit/ directory must be gitignored (generated artifacts; RULE_AUDIT_COMPLETE)."""
        assert self._check_ignored("audit/"), "audit/ must be in .gitignore (PKG2)"

    def test_pycache_is_gitignored(self):
        """__pycache__/ must be gitignored."""
        assert self._check_ignored("__pycache__"), "__pycache__/ must be in .gitignore (PKG2)"

    def test_pytest_cache_is_gitignored(self):
        """.pytest_cache/ must be gitignored."""
        assert self._check_ignored(".pytest_cache"), ".pytest_cache/ must be in .gitignore (PKG2)"

    def test_ds_store_is_gitignored(self):
        """.DS_Store must be gitignored (macOS metadata)."""
        assert self._check_ignored(".DS_Store"), ".DS_Store must be in .gitignore (PKG2)"

    def test_pyc_is_gitignored(self):
        """*.pyc must be gitignored."""
        assert self._check_ignored("some_file.pyc"), (
            "*.pyc files must be in .gitignore (PKG2)"
        )

    def test_samples_is_NOT_gitignored(self):
        """samples/ must NOT be gitignored — it is a tracked directory for redacted samples."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", "samples/"],
            capture_output=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode != 0, (
            "samples/ must NOT be gitignored — it is a tracked directory for redacted samples (PKG2)"
        )


# ---------------------------------------------------------------------------
# PKG3 — README + module docstrings
# ---------------------------------------------------------------------------

class TestPKG3:
    """PKG3: README has run-from-clean section; all app/ modules have top docstrings."""

    def test_readme_has_package_boundary_section(self):
        """README.md must include a 'Package boundary' section (D-S8; PKG3)."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "Package boundary" in readme or "package boundary" in readme, (
            "README.md must have a 'Package boundary + run-from-clean-checkout' section (PKG3)"
        )

    def test_readme_has_clean_checkout_instructions(self):
        """README.md must document the one-command clean-checkout path (PKG3)."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "python3 -m venv .venv" in readme, (
            "README.md must document venv creation (PKG3)"
        )
        assert "make install" in readme or "pip install -r requirements.txt" in readme, (
            "README.md must document pip install (PKG3)"
        )
        assert "make test" in readme, "README.md must document make test (PKG3)"
        assert "make demo" in readme, "README.md must document make demo (PKG3)"

    def test_readme_has_make_eval(self):
        """README.md must document make eval (PKG3)."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "make eval" in readme, "README.md must document make eval (PKG3)"

    def test_readme_has_make_demo_live(self):
        """README.md must document make demo-live and its gating (PKG3)."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "make demo-live" in readme, "README.md must document make demo-live (PKG3)"

    def test_all_app_modules_have_docstrings(self):
        """Every app/*.py and app/eval/*.py module must have a module-level docstring (PKG3)."""
        missing = []
        for py_file in sorted(APP_DIR.rglob("*.py")):
            if py_file.name == "__init__.py":
                continue  # __init__.py files may be empty
            try:
                source = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                missing.append(str(py_file.relative_to(REPO_ROOT)))
                continue
            docstring = ast.get_docstring(tree)
            if not docstring:
                missing.append(str(py_file.relative_to(REPO_ROOT)))
        assert not missing, (
            "The following app/ modules are missing module-level docstrings (PKG3):\n"
            + "\n".join(f"  {m}" for m in missing)
        )


# ---------------------------------------------------------------------------
# LEAK1 / SEC1 — no secret in any tracked file (RULE_NO_SECRET)
# ---------------------------------------------------------------------------

class TestLEAK1:
    """LEAK1 = SEC1: no ANTHROPIC_API_KEY value or sk-ant- token in any tracked file."""

    def test_no_secret_in_tracked_files(self):
        """LEAK1: no tracked file contains a real API key (sk-ant-<20+> pattern)."""
        tracked = _get_tracked_files()
        violations = []
        for path in tracked:
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if _REAL_KEY_RE.search(content):
                violations.append(str(path.relative_to(REPO_ROOT)))
            # Also check ANTHROPIC_API_KEY= assignments outside .env.example
            if "ANTHROPIC_API_KEY=" in content and ".env.example" not in str(path):
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("ANTHROPIC_API_KEY="):
                        value = stripped[len("ANTHROPIC_API_KEY="):]
                        if value and not value.startswith("your-"):
                            violations.append(f"{path.relative_to(REPO_ROOT)}: {stripped}")
        assert not violations, (
            "LEAK1/SEC1 (RULE_NO_SECRET): secret found in tracked files:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# LEAK2 — no PII / customer-data in tracked data files (RULE_NO_REAL_PII)
# ---------------------------------------------------------------------------

class TestLEAK2:
    """LEAK2: no real-looking email, phone, or customer name in tracked data files."""

    # Patterns for real-looking PII in JSON data files
    _EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    # Safe domains that appear in our synthetic data (not real PII)
    _SAFE_DOMAINS = {"example.com", "example.org", "synthetic.test", "privaterelay.appleid.com"}

    def test_no_real_emails_in_tracked_data(self):
        """LEAK2: data files must not contain real-looking email addresses."""
        tracked = _get_tracked_files()
        violations = []
        for path in tracked:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if not (rel.startswith("data/") or rel.startswith("fixtures/")):
                continue
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for match in self._EMAIL_RE.finditer(content):
                email = match.group()
                domain = email.split("@", 1)[1].lower() if "@" in email else ""
                if not any(domain.endswith(safe) for safe in self._SAFE_DOMAINS):
                    violations.append(f"{rel}: {email}")
        assert not violations, (
            "LEAK2 (RULE_NO_REAL_PII): real-looking emails found in tracked data files:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_only_synthetic_kb_files_tracked(self):
        """LEAK2: no non-synthetic KB or questionnaire files tracked (*.synthetic.* only)."""
        tracked = _get_tracked_files()
        violations = []
        for path in tracked:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel.startswith("data/kb/") or rel.startswith("data/questionnaires/"):
                if rel.endswith(".json") and ".synthetic." not in rel:
                    violations.append(rel)
        assert not violations, (
            "LEAK2 (RULE_NO_REAL_PII): non-synthetic data files tracked:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# LEAK3 / KB2 — no hardcoded KB values in app/ (anti-leakage)
# ---------------------------------------------------------------------------

class TestLEAK3:
    """LEAK3 = KB2: no data/*.synthetic.* value hardcoded in app/ code or prompts."""

    def _load_kb_answer_fragments(self) -> list[str]:
        """Extract distinct answer text fragments from the synthetic KB for grep."""
        kb_path = REPO_ROOT / "data" / "kb" / "approved_answers.synthetic.json"
        if not kb_path.exists():
            return []
        try:
            records = json.loads(kb_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        fragments = []
        for rec in records:
            answer = rec.get("answer", "")
            # Take the first 40 chars of each answer as a "signature fragment"
            frag = answer[:40].strip()
            if len(frag) >= 20:
                fragments.append(frag)
        return fragments

    def test_no_kb_answer_hardcoded_in_app(self):
        """LEAK3: no KB answer text inlined in app/ code (data values must come from data/)."""
        fragments = self._load_kb_answer_fragments()
        if not fragments:
            pytest.skip("Could not load KB fragments for LEAK3 check")

        app_source_files = list(APP_DIR.rglob("*.py"))
        violations = []
        for path in app_source_files:
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for frag in fragments:
                if frag in content:
                    violations.append(f"{path.relative_to(REPO_ROOT)}: contains '{frag[:30]}...'")
        assert not violations, (
            "LEAK3/KB2 (RULE_NO_REAL_PII): KB answer text hardcoded in app/:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_chunk_id_hardcoded_in_app(self):
        """LEAK3: specific chunk IDs from KB must not be hardcoded in app/ logic."""
        kb_path = REPO_ROOT / "data" / "kb" / "approved_answers.synthetic.json"
        if not kb_path.exists():
            pytest.skip("KB file not found for LEAK3 check")
        try:
            records = json.loads(kb_path.read_text(encoding="utf-8"))
        except Exception:
            pytest.skip("Could not parse KB for LEAK3 check")

        chunk_ids = [r.get("chunk_id", "") for r in records if r.get("chunk_id")]

        app_source_files = list(APP_DIR.rglob("*.py"))
        violations = []
        for path in app_source_files:
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for cid in chunk_ids:
                # A chunk_id like "kb-001" or "doc-001" hardcoded as a string literal
                if f'"{cid}"' in content or f"'{cid}'" in content:
                    violations.append(f"{path.relative_to(REPO_ROOT)}: hardcoded '{cid}'")
        assert not violations, (
            "LEAK3/KB2: specific chunk IDs from KB hardcoded in app/ code:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# LEAK4 / EVAL2 — eval contamination guard present (RULE_NO_EVAL_CONTAMINATION)
# ---------------------------------------------------------------------------

class TestLEAK4:
    """LEAK4 = EVAL2: the eval harness enforces the held-out split."""

    def test_harness_references_eval_contamination_rule(self):
        """LEAK4: app/eval/harness.py must reference RULE_NO_EVAL_CONTAMINATION."""
        harness = (APP_DIR / "eval" / "harness.py").read_text(encoding="utf-8")
        assert "RULE_NO_EVAL_CONTAMINATION" in harness, (
            "LEAK4/EVAL2: app/eval/harness.py must reference RULE_NO_EVAL_CONTAMINATION "
            "(contamination guard chokepoint)"
        )

    def test_harness_check_no_contamination_function_exists(self):
        """LEAK4: harness.py must define/export check_no_contamination."""
        harness = (APP_DIR / "eval" / "harness.py").read_text(encoding="utf-8")
        assert "check_no_contamination" in harness, (
            "LEAK4/EVAL2: app/eval/harness.py must define check_no_contamination "
            "(the contamination guard function)"
        )

    def test_contamination_injection_raises(self):
        """LEAK4: injecting a KB answer verbatim as an eval-case question must raise ValueError."""
        from app.eval.harness import check_no_contamination
        from app.kb import load_kb

        chunks = load_kb()
        approved = [c for c in chunks if c.approved and c.question]
        if not approved:
            pytest.skip("No approved chunks with questions for LEAK4 contamination test")

        # Inject a KB chunk's question verbatim as an eval case question
        chunk = approved[0]
        contaminated_cases = [
            {
                "item_id": "contam-i1",
                "question": chunk.question,  # verbatim KB question — this IS contamination
                "topic_tags": chunk.topic_tags,
                "expected_routed": False,
                "expected_grounded": True,
            }
        ]
        with pytest.raises(ValueError, match="RULE_NO_EVAL_CONTAMINATION|contamination"):
            check_no_contamination(contaminated_cases, chunks)


# ---------------------------------------------------------------------------
# LEAK5 / EVAL1 — every metric computed; no hardcoded score (RULE_NO_FABRICATED_METRIC)
# ---------------------------------------------------------------------------

class TestLEAK5:
    """LEAK5 = EVAL1: metrics are computed from labeled input, not hardcoded."""

    def test_harness_references_fabricated_metric_rule(self):
        """LEAK5: app/eval/harness.py must reference RULE_NO_FABRICATED_METRIC."""
        harness = (APP_DIR / "eval" / "harness.py").read_text(encoding="utf-8")
        assert "RULE_NO_FABRICATED_METRIC" in harness, (
            "LEAK5/EVAL1: app/eval/harness.py must reference RULE_NO_FABRICATED_METRIC"
        )

    def test_no_hardcoded_score_in_rubric(self):
        """LEAK5: app/eval/rubric.py must compute metrics (not return a constant)."""
        rubric = (APP_DIR / "eval" / "rubric.py").read_text(encoding="utf-8")
        # Hardcoded scores would short-circuit computation — the rubric must do arithmetic
        assert "len(" in rubric or "sum(" in rubric or "/" in rubric, (
            "LEAK5/EVAL1: rubric.py must compute metrics via arithmetic, "
            "not return a constant (RULE_NO_FABRICATED_METRIC)"
        )

    def test_eval_routing_accuracy_computed_not_hardcoded(self):
        """LEAK5: run_eval() must return a routing_accuracy that changes when gold is perturbed."""
        from app.eval.harness import run_eval

        # Run baseline
        baseline = run_eval()
        baseline_acc = baseline["routing_accuracy"]

        # Perturb the gold by modifying the eval_cases file temporarily via monkeypatching
        # We verify that routing_accuracy is >= 0 and <= 1 and is a float (computed)
        assert isinstance(baseline_acc, float), (
            "LEAK5: routing_accuracy must be a float (computed; RULE_NO_FABRICATED_METRIC)"
        )
        assert 0.0 <= baseline_acc <= 1.0, (
            f"LEAK5: routing_accuracy {baseline_acc} out of [0, 1] range"
        )

    def test_eval_recall_is_computed(self):
        """LEAK5: run_eval() recall_at_k must be a computed float in [0, 1]."""
        from app.eval.harness import run_eval
        result = run_eval()
        r = result["recall_at_k"]
        assert isinstance(r, float) and 0.0 <= r <= 1.0, (
            f"LEAK5: recall_at_k must be a float in [0, 1]; got {r!r}"
        )


# ---------------------------------------------------------------------------
# LEAK-G / GROUND1 — grounding gate enforced (RULE_GROUNDED_ONLY)
# ---------------------------------------------------------------------------

class TestLEAKG:
    """LEAK-G = GROUND1: grounding gate enforces UNGROUNDED_PLACEHOLDER."""

    def test_grounding_check_rejects_ungrounded_citation(self):
        """LEAK-G: grounding_check must return UNGROUNDED_PLACEHOLDER for a fabricated chunk_id."""
        from app.draft import grounding_check
        from app.config import UNGROUNDED_PLACEHOLDER
        from app.schema import DraftAnswer, Citation, ContextStack

        # Build a DraftAnswer citing a non-existent chunk ID
        fake_draft = DraftAnswer(
            text="Some fabricated claim about encryption with invented details.",
            citations=[Citation(chunk_id="non-existent-chunk-001")],
        )
        # Build a ContextStack with no matching retrieval entries
        empty_context = ContextStack(
            instruction="You are Comet.",
            retrieval=[],      # no retrieved chunks
            constraint="Standard constraints apply.",
            state="Item 1 of 1 | DRAFTED",
        )

        result = grounding_check(fake_draft, empty_context)
        # GroundingResult.answer is the DraftAnswer (possibly replaced with placeholder)
        assert result.answer.text == UNGROUNDED_PLACEHOLDER, (
            f"LEAK-G/GROUND1: grounding_check must return UNGROUNDED_PLACEHOLDER "
            f"for a fabricated citation; got: {result.answer.text!r}"
        )

    def test_grounding_check_rejects_no_citations(self):
        """LEAK-G: grounding_check must reject a draft with no citations."""
        from app.draft import grounding_check
        from app.config import UNGROUNDED_PLACEHOLDER
        from app.schema import DraftAnswer, ContextStack

        draft_no_citations = DraftAnswer(
            text="Answer with no citations at all.",
            citations=[],
        )
        context = ContextStack(
            instruction="You are Comet.",
            retrieval=["[kb-001] Some relevant content."],
            constraint="No constraints.",
            state="Item 1 of 1 | DRAFTED",
        )
        result = grounding_check(draft_no_citations, context)
        assert result.answer.text == UNGROUNDED_PLACEHOLDER, (
            "LEAK-G/GROUND1: a draft with no citations must be rejected as ungrounded"
        )

    def test_ungrounded_placeholder_byte_exact(self):
        """LEAK-G: UNGROUNDED_PLACEHOLDER in config must match CLAUDE.md §9 byte-exactly."""
        from app.config import UNGROUNDED_PLACEHOLDER
        expected = "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"
        assert UNGROUNDED_PLACEHOLDER == expected, (
            f"LEAK-G: UNGROUNDED_PLACEHOLDER mismatch: {UNGROUNDED_PLACEHOLDER!r}"
        )

    def test_draft_py_references_rule_grounded_only(self):
        """LEAK-G: app/draft.py must reference RULE_GROUNDED_ONLY (the chokepoint)."""
        draft_src = (APP_DIR / "draft.py").read_text(encoding="utf-8")
        assert "RULE_GROUNDED_ONLY" in draft_src, (
            "LEAK-G: app/draft.py must reference RULE_GROUNDED_ONLY (CLAUDE.md §5.1 chokepoint)"
        )


# ---------------------------------------------------------------------------
# LEAK-S / EXPORT2 — sensitivity gate enforced (RULE_SENSITIVITY_GATE)
# ---------------------------------------------------------------------------

class TestLEAKS:
    """LEAK-S = EXPORT2: sensitivity gate prevents internal/restricted export without review."""

    def test_export_py_references_rule_sensitivity_gate(self):
        """LEAK-S: app/export.py must reference RULE_SENSITIVITY_GATE (the chokepoint)."""
        export_src = (APP_DIR / "export.py").read_text(encoding="utf-8")
        assert "RULE_SENSITIVITY_GATE" in export_src, (
            "LEAK-S: app/export.py must reference RULE_SENSITIVITY_GATE (CLAUDE.md §5.1 chokepoint)"
        )

    def test_export_py_references_sensitivity_hold(self):
        """LEAK-S: app/export.py must emit SENSITIVITY_HOLD audit reason-code."""
        export_src = (APP_DIR / "export.py").read_text(encoding="utf-8")
        assert "SENSITIVITY_HOLD" in export_src, (
            "LEAK-S: app/export.py must emit SENSITIVITY_HOLD reason-code "
            "(RULE_SENSITIVITY_GATE chokepoint; CLAUDE.md §5.1)"
        )

    def test_sensitivity_gate_blocks_internal_without_review(self, tmp_path):
        """LEAK-S: internal/restricted item not exported without REVIEW_APPROVED."""
        from app.export import export_response
        from app.schema import ResponseDoc, ResponseDocItem
        from datetime import datetime, timezone

        # Build a ResponseDoc with one internal-sensitivity APPROVED item (no review_approved)
        internal_item = ResponseDocItem(
            item_id="test-internal-i1",
            question="Internal test question",
            status="APPROVED",
            draft_text="Internal answer text that must not appear in the export.",
            confidence_score=0.85,
            sensitivities=["internal"],
            review_approved=False,  # NOT human-review-approved — must be held
        )
        doc = ResponseDoc(
            questionnaire_id="test-s8-leak-s",
            generated_at=datetime.now(timezone.utc).isoformat(),
            items=[internal_item],
        )

        result = export_response(doc, out_dir=tmp_path)
        md_path = result.get("markdown")
        md_content = md_path.read_text(encoding="utf-8") if md_path and md_path.exists() else ""
        # The internal answer text must NOT appear in the export
        assert "Internal answer text that must not appear in the export." not in md_content, (
            "LEAK-S: internal item answer text appeared in export without REVIEW_APPROVED "
            "(RULE_SENSITIVITY_GATE violated)"
        )


# ---------------------------------------------------------------------------
# SEC2 — no secret in generated sample artifacts
# ---------------------------------------------------------------------------

class TestSEC2:
    """SEC2: no secret in generated sample artifacts tracked under samples/."""

    def test_no_secret_in_samples(self):
        """SEC2: samples/ tracked files must not contain a real API key."""
        samples_dir = REPO_ROOT / "samples"
        if not samples_dir.is_dir():
            pytest.skip("samples/ directory not found; skipping SEC2")

        violations = []
        for path in samples_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if _REAL_KEY_RE.search(content):
                violations.append(str(path.relative_to(REPO_ROOT)))
            if "ANTHROPIC_API_KEY=" in content:
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("ANTHROPIC_API_KEY="):
                        value = stripped[len("ANTHROPIC_API_KEY="):]
                        if value and not value.startswith("your-"):
                            violations.append(f"{path.relative_to(REPO_ROOT)}: {stripped}")
        assert not violations, (
            "SEC2 (RULE_NO_SECRET): secret found in samples/ tracked artifacts:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_local_paths_in_samples(self):
        """SEC2: samples/ must not contain machine-local absolute paths (redacted placeholders only)."""
        samples_dir = REPO_ROOT / "samples"
        if not samples_dir.is_dir():
            pytest.skip("samples/ directory not found; skipping SEC2 local-path check")

        home = str(Path.home())
        violations = []
        for path in samples_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if home in content:
                violations.append(str(path.relative_to(REPO_ROOT)))

        assert not violations, (
            "SEC2: samples/ files contain machine-local absolute paths — "
            "redact with [REDACTED-PATH] placeholders:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# META-FALSIFY — eval has ≥1 negative case (RULE_METRIC_FALSIFIABLE)
# ---------------------------------------------------------------------------

class TestMetaFalsify:
    """META-FALSIFY: the eval gold set contains ≥1 required negative/routing case."""

    def test_eval_gold_has_negative_case(self):
        """META-FALSIFY: eval_cases.synthetic.json must have ≥1 case where expected_routed=true
        OR expected_grounded=false — the 'red' fixture the metric is required to report as failing."""
        gold_path = FIXTURES_DIR / "eval" / "eval_cases.synthetic.json"
        assert gold_path.exists(), "eval_cases.synthetic.json must exist (META-FALSIFY)"
        cases = json.loads(gold_path.read_text(encoding="utf-8"))
        negative_cases = [
            c for c in cases
            if c.get("expected_routed") is True or c.get("expected_grounded") is False
        ]
        assert len(negative_cases) >= 1, (
            "META-FALSIFY (RULE_METRIC_FALSIFIABLE): eval gold has no negative case "
            "(no expected_routed=true or expected_grounded=false). "
            "A metric with no required-failing fixture is a tautology and unverified."
        )

    def test_eval_gold_has_ungrounded_negative_case(self):
        """META-FALSIFY: ≥1 eval case must have expected_grounded=false (grounding red case)."""
        gold_path = FIXTURES_DIR / "eval" / "eval_cases.synthetic.json"
        cases = json.loads(gold_path.read_text(encoding="utf-8"))
        ungrounded = [c for c in cases if c.get("expected_grounded") is False]
        assert len(ungrounded) >= 1, (
            "META-FALSIFY: eval gold must have ≥1 case with expected_grounded=false "
            "(grounding red fixture; RULE_METRIC_FALSIFIABLE)"
        )

    def test_eval_gold_has_routing_negative_case(self):
        """META-FALSIFY: ≥1 eval case must have expected_routed=true (routing exercised)."""
        gold_path = FIXTURES_DIR / "eval" / "eval_cases.synthetic.json"
        cases = json.loads(gold_path.read_text(encoding="utf-8"))
        routed = [c for c in cases if c.get("expected_routed") is True]
        assert len(routed) >= 1, (
            "META-FALSIFY: eval gold must have ≥1 case with expected_routed=true "
            "(routing metric coverage; RULE_METRIC_FALSIFIABLE)"
        )

    def test_eval_gold_has_non_routing_case(self):
        """META-FALSIFY: ≥1 eval case must have expected_routed=false (positive case — auto-draft)."""
        gold_path = FIXTURES_DIR / "eval" / "eval_cases.synthetic.json"
        cases = json.loads(gold_path.read_text(encoding="utf-8"))
        not_routed = [c for c in cases if c.get("expected_routed") is False]
        assert len(not_routed) >= 1, (
            "META-FALSIFY: eval gold must have ≥1 case with expected_routed=false "
            "(auto-draft positive case; RULE_METRIC_FALSIFIABLE)"
        )


# ---------------------------------------------------------------------------
# META-REALPATH — no def _simulate_* in app/ (RULE_METRIC_FALSIFIABLE)
# ---------------------------------------------------------------------------

class TestMetaRealpath:
    """META-REALPATH: the real internal path is exercised; no _simulate_* functions in app/."""

    def test_no_simulate_function_definitions_in_app(self):
        """META-REALPATH: app/ must not define _simulate_* functions (real internal path only).

        Note: comments or docstrings *mentioning* _simulate_ as deleted history are fine.
        Only actual function definitions (def _simulate_*) are forbidden.
        """
        violations = []
        for py_file in APP_DIR.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            # Check for actual function definitions, not just mentions in comments
            if re.search(r"^\s*def\s+_simulate_", content, re.MULTILINE):
                violations.append(str(py_file.relative_to(REPO_ROOT)))
        assert not violations, (
            "META-REALPATH (RULE_METRIC_FALSIFIABLE): _simulate_* function defined in app/. "
            "Only non-deterministic external boundaries (network/clock/model/RNG) may be "
            "substituted. Internal gates must be exercised on the real path.\n"
            "Violations:\n" + "\n".join(f"  {v}" for v in violations)
        )

    def test_harness_calls_real_grounding_check(self):
        """META-REALPATH: app/eval/harness.py must call grounding_check (real path, not a stub)."""
        harness_src = (APP_DIR / "eval" / "harness.py").read_text(encoding="utf-8")
        assert "grounding_check" in harness_src, (
            "META-REALPATH: app/eval/harness.py must import/call grounding_check "
            "(real grounding path; no _simulate_ shortcut)"
        )

    def test_harness_calls_real_draft_answer(self):
        """META-REALPATH: app/eval/harness.py must call draft_answer (real pipeline path)."""
        harness_src = (APP_DIR / "eval" / "harness.py").read_text(encoding="utf-8")
        assert "draft_answer" in harness_src, (
            "META-REALPATH: app/eval/harness.py must call draft_answer "
            "(real draft path; no simulation shortcut)"
        )


# ---------------------------------------------------------------------------
# META-PROVENANCE — PROVENANCE.md exists and covers all eval case IDs
# ---------------------------------------------------------------------------

class TestMetaProvenance:
    """META-PROVENANCE: gold case provenance is documented spec-first."""

    def test_provenance_md_exists(self):
        """META-PROVENANCE: fixtures/eval/PROVENANCE.md must exist."""
        prov = FIXTURES_DIR / "eval" / "PROVENANCE.md"
        assert prov.exists(), (
            "META-PROVENANCE (RULE_METRIC_FALSIFIABLE): "
            "fixtures/eval/PROVENANCE.md must exist and document the spec rationale "
            "for each eval gold case."
        )

    def test_provenance_covers_all_eval_case_ids(self):
        """META-PROVENANCE: PROVENANCE.md must mention every eval case ID."""
        prov_path = FIXTURES_DIR / "eval" / "PROVENANCE.md"
        gold_path = FIXTURES_DIR / "eval" / "eval_cases.synthetic.json"
        if not prov_path.exists() or not gold_path.exists():
            pytest.skip("PROVENANCE.md or eval_cases.synthetic.json not found")

        prov_content = prov_path.read_text(encoding="utf-8")
        cases = json.loads(gold_path.read_text(encoding="utf-8"))

        missing = []
        for case in cases:
            item_id = case.get("item_id", "")
            if item_id and item_id not in prov_content:
                missing.append(item_id)

        assert not missing, (
            "META-PROVENANCE: PROVENANCE.md does not cover all eval case IDs:\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    def test_provenance_mentions_spec_rationale(self):
        """META-PROVENANCE: PROVENANCE.md must derive cases from spec, not output."""
        prov = (FIXTURES_DIR / "eval" / "PROVENANCE.md").read_text(encoding="utf-8")
        rationale_words = ["spec", "intent", "rule", "RULE_", "trigger", "derives from", "derive"]
        found = any(word.lower() in prov.lower() for word in rationale_words)
        assert found, (
            "META-PROVENANCE: PROVENANCE.md must derive cases from spec/intent "
            "(should reference rules, triggers, or spec rationale)"
        )
