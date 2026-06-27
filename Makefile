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

.PHONY: install integrity test demo demo-live eval

install:
	pip install -r requirements.txt

integrity:
	bash scripts/check_graded_artifacts.sh

test: integrity
	pytest -q

demo:
	python scripts/run_demo.py

demo-live:
	python scripts/run_live_draft.py

eval: integrity
	python -m app.eval.harness
