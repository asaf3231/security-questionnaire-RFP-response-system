# Reindeer — Comet RFP/Security-Questionnaire Response Agent
# Usage: make <target>
#
# Targets:
#   install    — install pinned dependencies into the active venv
#   test       — run the offline deterministic pytest suite (no .env, no network)
#   demo       — mocked end-to-end pipeline (MockLLM, no network)
#   demo-live  — gated live Claude draft (requires ANTHROPIC_API_KEY; still no external send)
#   eval       — offline deterministic evaluation harness (computed metrics; no network)

.PHONY: install test demo demo-live eval

install:
	pip install -r requirements.txt

test:
	pytest -q

demo:
	python scripts/run_demo.py

demo-live:
	python scripts/run_live_draft.py

eval:
	python -m app.eval.harness
