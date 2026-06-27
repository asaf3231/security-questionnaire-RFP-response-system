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
