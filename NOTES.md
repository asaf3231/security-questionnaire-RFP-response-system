# NOTES.md — Decisions, Open Questions & Handback Pointers

Project: **Reindeer RFP / Security-Questionnaire Response Agent (codename "Comet")**
Maintained by: Asaf (PM)

> Decisions (the *why*) + per-stage handback **pointers** live here. Numbers live in `FACTS.md`; rules
> in `CLAUDE.md`; status in `PLAN.md`; the checkpoint in `STATE.md`. Never paste a handback payload
> here — it stays on disk under `handbacks/stage-<N>.md`; this file gets only the pointer line:
> `Stage <N> ✅ — handbacks/stage-<N>.md · verdict <APPROVE> · commit <sha>`.

---

## Genesis decisions (2026-06-27)

### D-1 — Deliverable shape + API posture *(graded contract)*
**Decision:** a Python **service repo + CLI**. The **deterministic offline pytest suite (mocked LLM,
seeded) is the graded "Restart & Run All" core**; a separate, explicitly **gated live lane**
(`make demo-live`) uses the provided Claude API key for a real-draft demo.
**Reason:** the assignment allows "working, mocked, or pseudo" and provides a key; the offline-core +
gated-live split (mirroring the `Reference/` project) gives reproducible grading *and* a real-model
demo without making the suite non-deterministic or network-dependent.
**Impact:** `MockLLM` is the default `LLMProvider`; `ClaudeLLM` is lazy + gated; `ENV4` import-safety
and `make test` offline are first-class. See [[CLAUDE.md §1]].

### D-2 — KB retrieval = deterministic lexical (`rank_bm25`) *(graded contract)*
**Decision:** deterministic lexical retrieval via the established **`rank_bm25`** library (pinned,
**not** hand-rolled) + a topic/sensitivity tag filter, over **paragraph / approved-answer chunks** as
the atomic unit. Primary metric **Recall@K**.
**Reason:** Asaf (AI-Ops principle B): recall-first — the LLM can't use evidence it doesn't see;
deterministic retrieval keeps the offline suite reproducible and the confidence signal explainable;
paragraph-level chunks avoid context dilution while keeping complete context for generation.
**Impact:** `RETRIEVAL_TOP_K`/`BM25_K1`/`BM25_B`/`RECALL_AT_K_TARGET` in §9; `RET1`–`RET3`.

### D-3 — Hybrid confidence = property validators + LLM rationale *(graded contract)*
**Decision:** the numerical confidence is a **deterministic** function of retrieval quality + grounding
checks ("property validators"); the **LLM writes the human-readable rationale only** and never the
number.
**Reason:** Asaf (principle D): self-reported LLM confidence is poorly calibrated; a deterministic gate
is testable and the rationale makes the audit log *defensible* to Security/Legal/AE stakeholders.
**Impact:** `CONF1`–`CONF3`; the gate drives `RULE_HITM_REVIEW_TRIGGER`.

### D-4 — Non-code deliverables are first-class stages
**Decision:** agents author the Brief/Deck and Technical Appendix as repo artifacts (Stage 9); Asaf
delivers the live 20-minute presentation.
**Reason:** the assignment lists all four deliverables; the two written ones belong in the repo and
must trace every number to `FACTS.md`.
**Impact:** Stage 9; `DOC1`–`DOC2`.

### D-5 — Harness Engineering: grep-enforceable `RULE_*` registry *(graded contract)*
**Decision:** every governance/anti-leakage/safety boundary is a uniquely-named `RULE_*` (string
constant in `app/config.py`) with a code chokepoint, an audit reason-code, and a QA ID — the agent is
restrained **by code, not by prompt text**. HITM is enforced: the agent **may never self-approve**;
routing triggers (high-risk tag / ambiguity / low-confidence) are code, not suggestions.
**Reason:** Asaf (principles C + E): a boundary verifiable by grepping code/logs is auditable; a
prompt-only boundary is not. A `RULE_*` with no chokepoint or no QA check is a spine defect.
**Impact:** `CLAUDE.md` §5 registry; `RULE1`–`RULE2`; the seven anti-leakage `LEAK*`.

### D-6 — Agent Context Stack ("backpack")
**Decision:** every turn assembles a 4-layer context stack — Instruction / Retrieval / Constraint /
State — in `app/context_stack.py`; **nothing outside the retrieved chunks reaches the model**.
**Reason:** Asaf (principle A): structured context bounds dilution + grounding leakage and makes the
prompt a single auditable chokepoint.
**Impact:** `CTX1`–`CTX4`; cross-checks `RULE_GROUNDED_ONLY`.

### D-7 — Codename "Comet" *(proposal — Asaf may override)*
**Decision (proposed):** call the agent **"Comet"** (a reindeer; fits Reindeer + the speed/clarity
connotation). Used in headers only; not load-bearing. **Open for Asaf to override.**

---

## Anti-leakage — what "leakage" means here (summary; full in `CLAUDE.md` §5.2)
Seven concrete, grep/test-enforced failures, each a `RULE_*`: (1) grounding/hallucination
(`RULE_GROUNDED_ONLY`), (2) secret (`RULE_NO_SECRET`), (3) PII/customer-data (`RULE_NO_REAL_PII`),
(4) eval/train-test contamination (`RULE_NO_EVAL_CONTAMINATION`), (5) fabricated metrics
(`RULE_NO_FABRICATED_METRIC`), (6) sensitivity-tag (`RULE_SENSITIVITY_GATE`), (7) external-send
(`RULE_NO_EXTERNAL_SEND`).

---

## Open questions

- **OQ-1** — ~~pin `DRAFT_MODEL`~~ **RESOLVED 2026-06-27 (Asaf): `claude-sonnet-4-6` locked** — optimal
  balance for a lightweight agentic workflow; best for interactive coding. Already the §9 default, so no
  code change. Offline graded path uses `MockLLM` regardless; this id binds only the gated live lane.
- **OQ-2** — ~~export format~~ **RESOLVED 2026-06-27 (Asaf): support BOTH** — a **Markdown** response
  doc (`exports/*.md`, narrative; for Security/Legal) **and** a **CSV grid** (`exports/*.csv`, one row
  per item: question / status / confidence / queue / citations; for Sales/AEs). Both land at Stage 5
  (`EXPORT1`); both obey `RULE_SENSITIVITY_GATE` + `RULE_NO_EXTERNAL_SEND`.

## Codename — CONFIRMED
**"Comet"** confirmed by Asaf 2026-06-27 (D-7 promoted from proposal to locked).

---

## Handback pointers (filled per stage; pointer-not-copy)
_(none yet — Stage 0 is PM-authored spine; first executer handback lands at Stage 1.)_
