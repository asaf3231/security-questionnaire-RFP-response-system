# Comet — Technical Appendix
### Reindeer RFP / Security-Questionnaire Response Agent

> Consistent with the shipped code on branch `redteam/crazy-testing`. Constants are named per
> `CLAUDE.md` §9 / `app/config.py`; verified numbers live in `FACTS.md`. This appendix describes
> mechanism, not metrics.

---

## 1. Pipeline & module map
`app/pipeline.py` orchestrates, per item:

```
INTAKE → refine_query (Stage 10) → retrieve → assemble_context → draft_answer + grounding_check
       → score_confidence → route_for_review → update_status → write_audit → export_response
```

| Module | Responsibility | Key rule |
|---|---|---|
| `app/config.py` | constants, `RULE_*` strings, lazy `_get_claude()`, `.env` load | `RULE_NO_SECRET` |
| `app/schema.py` | Pydantic models (below) | — |
| `app/kb.py` | load + validate KB / questionnaire / policy tags | `KB1`/`DATA1` |
| `app/retrieval.py` | `rank_bm25` + tag/sensitivity filter; build-once `Retriever` | `RET1`–`RET3` |
| `app/query_optimizer.py` | `refine_query` + depth-aware `strip_thinking_block` (live-lane only) | `QREF*` |
| `app/context_stack.py` | the 4-layer backpack assembler | `CTX1`–`CTX4` |
| `app/llm.py` | `LLMProvider` → `MockLLM` (offline) / `ClaudeLLM` (gated live) | `DRAFT1`/`DRAFT2` |
| `app/draft.py` | `draft_answer` + `grounding_check` | `RULE_GROUNDED_ONLY` |
| `app/confidence.py` | deterministic score + LLM rationale-only | `CONF1`–`CONF3` |
| `app/routing.py` | the 5 review triggers | `RULE_HITM_REVIEW_TRIGGER` |
| `app/state.py` | state machine + no-self-approve guard | `RULE_NO_SELF_APPROVE` |
| `app/audit.py` | append-only JSONL writer + redaction | `RULE_AUDIT_COMPLETE` |
| `app/export.py` | Markdown+CSV, approved-only, sensitivity gate | `RULE_NO_EXTERNAL_SEND` / `RULE_SENSITIVITY_GATE` |

## 2. Data schema (`app/schema.py`)
`QuestionnaireItem(item_id, question, topic_tags[])` · `RetrievedChunk(chunk_id, answer, source,
sensitivity, topic_tags[], bm25_score)` · `ContextStack(instruction, retrieval[], constraint, state,
question)` — `question` (default `""`) was added in Stage 10 so the original question reaches the draft
prompt (backward-compatible) · `Citation(chunk_id, source)` · `DraftAnswer(text, citations[])` ·
`ConfidenceResult(score, rationale)` · `RoutingDecision(should_route, queue, reason_code, rule)` ·
`AuditEvent(timestamp, questionnaire_id, item_id, event, from_state, to_state, rule, detail)` ·
`ResponseDoc(items[])` / `ResponseDocItem(..., sensitivities[], review_approved)`.

## 3. Prompt & tool design
- **The backpack is the only context the model sees.** `assemble_context` is the single place the prompt
  is built: Instruction (role) / Retrieval (`[chunk_id] text`, only the passed chunks) / Constraint
  (high-risk clause for high-risk items) / State ("Question X of Y") + the original question.
- **`MockLLM`** is deterministic and seeded (`RANDOM_SEED`); it never emits `<thinking>`; its
  `refine_query` is the identity default → the offline graded path is byte-identical.
- **`ClaudeLLM`** (live lane, `DRAFT_MODEL`, `DRAFT_TEMPERATURE=0.0`): wraps the API call; on
  timeout/error it degrades to `UNGROUNDED_PLACEHOLDER` (never a partial/invented answer).
- **`submit_answer` tool (live-lane structured citations).** The draft call uses Anthropic native
  **tool use**: it passes a `submit_answer` tool whose `input_schema` makes `answer` **and** `citations`
  (chunk_id array) *required*, forced via `tool_choice={"type":"tool","name":"submit_answer"}`. So
  citations are a **schema-required field**, not regex-scraped from prose — this removed the intermittent
  `cit=0` failure (model dropping inline `[chunk_id]` markers). Tool citations are validated against the
  retrieval layer (fabricated ids dropped, de-duped) and unioned with any inline markers; a text-only
  response falls back to the prose-parse path (`_extract_tool_answer` / `_known_chunk_ids`).
- **Query refinement (Stage 10):** `ClaudeLLM.refine_query` may reason inside `<thinking>…</thinking>`
  and emit keywords after it; `strip_thinking_block` (a deterministic, depth-aware, nested-safe scan)
  removes the reasoning so only clean keywords reach BM25, bounded by `MAX_REFINED_QUERY_CHARS` /
  `REFINE_MAX_TOKENS`; any failure degrades to the original question.
- **Design note (live evidence, 2026-06-28):** the *draft* `<thinking>` scaffold was removed — it made
  the live model emit reasoning prose and drop inline citations, so the grounding gate forced human
  review (see `redteam/LIVE_RUN_FINDINGS*.md`). A **defensive** `<thinking>` strip remains in
  `ClaudeLLM.draft` because the model may still emit reasoning unasked. The in-`<thinking>` self-checks
  were always **defense-in-depth UX, not enforcement** — enforcement is the code chokepoints.

## 4. Guardrails — the `RULE_*` registry (`CLAUDE.md` §5)
Each rule = one searchable identifier, one code chokepoint, one audit reason-code, one QA ID:
`RULE_GROUNDED_ONLY` (draft.py → `GROUNDING_FAIL`), `RULE_NO_SELF_APPROVE` (state.py →
`SELF_APPROVE_BLOCKED`), `RULE_HITM_REVIEW_TRIGGER` (routing.py → `ROUTED_*`), `RULE_NO_EXTERNAL_SEND`
(export.py → `EXTERNAL_SEND_BLOCKED`), `RULE_SENSITIVITY_GATE` (export.py+routing.py → `SENSITIVITY_HOLD`),
`RULE_NO_SECRET`, `RULE_NO_REAL_PII`, `RULE_NO_EVAL_CONTAMINATION`, `RULE_NO_FABRICATED_METRIC`,
`RULE_AUDIT_COMPLETE`, `RULE_SAFE_TERMINAL` (pipeline.py → `ERROR_TERMINAL`). Two governance-tier rules
(`RULE_GRADED_ARTIFACT_LOCK`, `RULE_METRIC_FALSIFIABLE`, §5.3) guard the *verification process* via the
`make` pre-flight (`scripts/check_graded_artifacts.sh`) + the `META-*` checks.

**Grounding gate (`RULE_GROUNDED_ONLY`)** rejects an answer unless: ≥ `GROUNDING_MIN_CITATIONS` cited
chunk; draft content covered by cited chunks ≥ `GROUNDING_COVERAGE_MIN`; and (Stage 7r) the cited
evidence addresses the question ≥ `GROUNDING_QUESTION_COVERAGE_MIN`. Otherwise → `UNGROUNDED_PLACEHOLDER`
+ route.

## 5. State machine (`app/state.py`)
`ITEM_STATES = INTAKE → RETRIEVED → DRAFTED → SCORED → {ROUTED_FOR_REVIEW → REVIEW_APPROVED |
REVIEW_REJECTED} → APPROVED → EXPORTED`. Illegal edges raise `InvalidTransition`. The agent may never
transition to APPROVED/EXPORTED — only `actor="human"` can (`SelfApproveBlocked` otherwise).
**Human review, three modes:** (1) `make demo` (offline) auto-simulates approval for
confident/non-sensitive items (still `actor="human"`); (2) `run_questionnaire.py --approve` is an
interactive per-item gate (`[a]pprove / [r]eject / [s]kip`); (3) `make demo-live` (gated live lane)
reviews **only the routed exceptions** — confident, non-routed drafts are auto-approved without a
prompt (mirroring `make demo`), and the human types `[a]pprove / [r]eject` only for items that
`RULE_HITM_REVIEW_TRIGGER` routed (ungrounded placeholders are left unreviewed). In every mode a routed
item walks the real path `ROUTED_FOR_REVIEW → REVIEW_APPROVED → APPROVED` and a reject becomes
`REVIEW_REJECTED` (stays unexported, rendered as "answer rejected"); auto-approval still goes through
`transition(actor="human")`. Each human decision writes its own `state_transition` audit event
(`RULE_NO_SELF_APPROVE`, `actor="human"`).

## 6. Reviewer routing (`app/routing.py`)
`RULE_HITM_REVIEW_TRIGGER`, precedence order (first match wins): (1) high-risk tag (`HIGH_RISK_TAGS`) →
`ROUTED_HIGH_RISK`; (2) ambiguous retrieval (top1−top2 BM25 gap < `AMBIGUITY_SCORE_MARGIN`) →
`ROUTED_AMBIGUOUS`; (3) confidence < `CONFIDENCE_REVIEW_THRESHOLD` → `ROUTED_LOW_CONFIDENCE`;
(4) internal/restricted sensitivity → `SENSITIVITY_REVIEW_QUEUE` ("compliance") → `ROUTED_SENSITIVE`
(Stage 7 / Option A); (5) ungrounded draft → `ROUTED_UNGROUNDED` (DN-QA50, **lowest** precedence — an
ungrounded answer still reaches a human even when no other trigger fired). Queue comes from the policy
`routing_map`, else `DEFAULT_REVIEWER_QUEUE`; all queues ⊆ `REVIEWER_QUEUES`.

## 7. Audit & logging (`app/audit.py`)
A single append-only JSONL writer emits exactly one `AuditEvent` per state transition and per tool call
— no silent gap (`RULE_AUDIT_COMPLETE`). Each event carries the `RULE_*` reason-code when one fired and a
`detail` object (computed numbers, retrieved `chunk_id`s, queue). Redaction scrubs any secret/email/phone
shape before write; **an audit record never contains a secret or unredacted real PII**. The audit log is
what makes an export defensible to Security/Legal.

## 8. Determinism, eval integrity & reproduction
The offline suite is the "Restart & Run All" equivalent: `make test` runs clean, network-free, no
secrets, fully deterministic (seeded `MockLLM`; deterministic `rank_bm25`; `DRAFT_TEMPERATURE=0.0`). The
eval (`make eval`) holds the questionnaire-under-test out of its KB (`RULE_NO_EVAL_CONTAMINATION`),
computes every metric from labeled fixtures (`RULE_NO_FABRICATED_METRIC`), and ships a **required
negative case** the grounding metric must catch — so the metric can go red. Reproduce from a clean
checkout: `python3 -m venv .venv && pip install -r requirements.txt && make test && make demo`. The live
draft is the separate gated `make demo-live` (the only Claude API path; still no external send).
