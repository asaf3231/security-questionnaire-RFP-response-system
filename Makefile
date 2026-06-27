# Reindeer — Comet RFP/Security-Questionnaire Response Agent
# Usage: make <target>
#
# Targets:
#   install    — install pinned dependencies into the active venv
#   integrity  — pre-flight graded-artifact lock (RULE_GRADED_ARTIFACT_LOCK); gates test/eval
#   test       — run the offline deterministic pytest suite (no .env, no network)
#   demo       — mocked end-to-end pipeline (MockLLM, no network)
#   demo-live  — gated live Claude draft (requires ANTHROPIC_API_KEY; still no external send)
#   eval       — offline deterministic evaluation harness (computed metrics; no network)
#
# Governance: `test` and `eval` depend on `integrity`, which aborts (non-zero) if the
# graded-artifact set (tests/, fixtures/) has modified/deleted lines vs HEAD without the
# human override ALLOW_GRADED_EDIT=1 (RULE_GRADED_ARTIFACT_LOCK; QA META-LOCK; CLAUDE.md §5.3).
#
# venv-clean: all python/pytest invocations use .venv/bin/python and .venv/bin/pytest.
# If .venv is missing, a clear bootstrap message is printed and the target exits non-zero.
# NEVER silently falls back to system python (that caused rank_bm25 import failures).

.PHONY: install integrity test demo demo-live eval

PY     := .venv/bin/python
PYTEST := .venv/bin/pytest

# Guard: abort with a bootstrap message if the venv is missing.
define check_venv
	@if [ ! -f "$(PY)" ]; then \
		echo ""; \
		echo "ERROR: .venv not found — bootstrap first:"; \
		echo "    python3 -m venv .venv && make install"; \
		echo ""; \
		exit 1; \
	fi
endef

install:
	pip install -r requirements.txt

integrity:
	bash scripts/check_graded_artifacts.sh

test: integrity
	$(call check_venv)
	$(PYTEST) -q

demo:
	$(call check_venv)
	$(PY) scripts/run_demo.py

demo-live:
	$(call check_venv)
	$(PY) scripts/run_live_draft.py

eval: integrity
	$(call check_venv)
	$(PY) -m app.eval.harness
