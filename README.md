# Reindeer — Comet RFP/Security-Questionnaire Response Agent

**Comet** is an internal AI agent that ingests security questionnaires and RFPs, drafts grounded
responses from a knowledge base of prior approved answers, scores confidence, routes low-confidence
or policy-sensitive items to the right human reviewer, tracks status, and produces an auditable,
exportable response document.

> **All data in this repo is synthetic/fake.** The knowledge base, questionnaires, and policy tags
> under `data/*.synthetic.*` are illustrative examples created for testing purposes only. They do
> not represent any real customer data, real security answers, or real product information.

---

## Run from a clean checkout

```bash
# 1. Create and activate a virtual environment (Python 3.11 or higher required)
python3 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\Activate.ps1

# 2. Install pinned dependencies
pip install -r requirements.txt
# or: make install

# 3. (Optional) Set up your environment file for the live lane
cp .env.example .env
# Then fill in ANTHROPIC_API_KEY — NEVER commit your .env

# 4. Run the offline deterministic test suite (no .env, no network required)
make test
```

The offline suite runs fully without a `.env` file or network access. It uses `MockLLM` (a
deterministic, seeded mock) — the graded offline path.

---

## Later stages (arriving as the project progresses)

- **`make demo`** — run the full pipeline end-to-end over the two demo cases using `MockLLM`
  (mocked LLM, no network). Arrives at Stage 6.
- **`make demo-live`** — gated live Claude draft using the real `anthropic` API (requires
  `ANTHROPIC_API_KEY` in `.env`). Still writes exports to local disk only — no external send.
  Arrives at Stage 6.
- **`make eval`** — run the offline evaluation harness (Recall@K, grounding rate, routing
  accuracy, confidence calibration). Arrives at Stage 7.

---

## Architecture summary

```
app/config.py      — all constants, RULE_* registry strings, lazy Claude getter
app/schema.py      — Pydantic models (QuestionnaireItem, DraftAnswer, AuditEvent, …)
app/kb.py          — KB + questionnaire + policy-tags load & validate
app/retrieval.py   — deterministic lexical retrieval via rank_bm25 (Stage 2)
app/context_stack.py — 4-layer "backpack" assembler (Stage 3)
app/llm.py         — MockLLM (offline) + ClaudeLLM (gated live lane) (Stage 3)
app/draft.py       — draft_answer + grounding_check (Stage 3)
app/confidence.py  — deterministic confidence scoring (Stage 4)
app/routing.py     — RULE_HITM_REVIEW_TRIGGER: routes risky items (Stage 4)
app/state.py       — item state machine; RULE_NO_SELF_APPROVE guard (Stage 4)
app/audit.py       — append-only JSONL audit log (Stage 5)
app/export.py      — response-doc renderer; RULE_NO_EXTERNAL_SEND (Stage 5)
app/pipeline.py    — end-to-end orchestration (Stage 6)
```

Governance is enforced in **code**, not prompts: every boundary is a `RULE_*` constant in
`app/config.py` with a single code chokepoint, an audit reason-code, and a test ID.

---

## Assumptions

- All KB and questionnaire data under `data/*.synthetic.*` is **entirely synthetic** — not derived
  from any real customer, prospect, or product.
- The offline graded path uses `MockLLM` (seeded, deterministic). The live lane (`make demo-live`)
  requires an `ANTHROPIC_API_KEY` but still never sends anything externally.
- Python 3.11+ is required. The service is OS-agnostic (no absolute paths; all paths via `pathlib`).

---

## Package boundary + run-from-clean-checkout

### What ships (runtime)

| Path | Role |
|---|---|
| `app/` | The Comet agent service — all modules (config, schema, kb, retrieval, context\_stack, llm, draft, confidence, routing, state, audit, export, pipeline, eval/) |
| `data/*.synthetic.*` | Bounded synthetic KB, questionnaires, policy tags — runtime inputs |
| `requirements.txt` | Pinned deps — install with `pip install -r requirements.txt` |
| `pyproject.toml` | Minimal package metadata (`requires-python >= 3.11`; packages = `app` + `app.eval`) |
| `.env.example` | Placeholder-only env template |
| `Makefile` | One-command run/test/demo/eval entry points |
| `README.md` | This file |
| `samples/` | ONE redacted demo export (`.md` + `.csv`) + audit (`.jsonl`) — shows output shape; not live data |

### Dev-only (excluded from any dist)

| Path | Role |
|---|---|
| `tests/` | Offline deterministic pytest suite |
| `fixtures/` | Labeled eval gold + Recall@K gold (held-out; synthetic) |
| `scripts/` | Demo runners (`run_demo.py`, `run_live_draft.py`) + integrity pre-flight |
| `exports/` | **gitignored** — machine-local generated response docs |
| `audit/` | **gitignored** — machine-local append-only JSONL audit logs |
| `.venv/` | **gitignored** — virtual environment |

### One-command clean-checkout path

All `make` targets require the venv to be set up first (they run `.venv/bin/python` /
`.venv/bin/pytest` — never system python). If `.venv` is missing, the target prints a clear
bootstrap message and exits non-zero.

```bash
# Bootstrap (once per clone)
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
make install                     # pip install -r requirements.txt into the venv

# Optional: set up the live lane
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY — NEVER commit your .env

# Run targets (all use .venv/bin/python — no manual venv activation needed after bootstrap)
make test       # offline deterministic pytest suite (no .env, no network; 315+ tests)
make demo       # end-to-end pipeline over both demo cases (MockLLM, no network)
make eval       # offline evaluation harness (Recall@K, grounding rate, routing accuracy, calibration)
make demo-live  # gated live Claude draft (requires ANTHROPIC_API_KEY; no external send)
```

### `make test` + `make eval` pre-flight

Before running the suite or eval, `make integrity` checks that the graded-artifact set
(`tests/`, `fixtures/`) has not been modified or deleted vs HEAD (`RULE_GRADED_ARTIFACT_LOCK`).
An add is allowed (new tests/fixtures); a modify or delete aborts the run. A failing test is a
**finding to report**, never fixed by editing the test.

### Governance boundary

- `RULE_NO_EXTERNAL_SEND` — export writes to local disk only; no email/HTTP-POST/upload.
- `RULE_NO_SELF_APPROVE` — the agent never transitions an item to `APPROVED`; only a human does.
- `RULE_SENSITIVITY_GATE` — `internal`/`restricted` items are held from export without human review.
- All 11 `RULE_*` identifiers are defined in `app/config.py` and enforced at their named chokepoints.

### Samples

The `samples/` directory contains one redacted demo output showing the export and audit shape.
Paths and timestamps are replaced with placeholders. All content is synthetic.
