# Comet — Architecture (code-accurate)

> Reindeer RFP / Security-Questionnaire Response Agent. Every box names the real module and the real
> behavior in the shipped code. Constants (e.g. `RETRIEVAL_TOP_K`, thresholds) live in `app/config.py`;
> verified numbers live in `FACTS.md`.

---

## End-to-end pipeline (per questionnaire item)

```
                 ┌─────────────────────────────────────────────┐
                 │  INPUT: data/questionnaires/*.synthetic.json │
                 │  (questionnaire_id + items[]; validated)      │
                 └─────────────────────────────────────────────┘
                                      │
                                      ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 1. INTAKE + QUERY REFINEMENT                                           │
   │    kb.load_questionnaire()  → validate (ValueError, not crash)         │
   │    pipeline.run_pipeline()  → item enters state INTAKE                 │
   │    query_optimizer.refine_query():                                     │
   │      • LIVE (ClaudeLLM): expand synonyms/technical terms,              │
   │        strip <thinking> → clean keywords                               │
   │      • OFFLINE (MockLLM): identity (query unchanged → determinism)     │
   └──────────────────────────────────────────────────────────────────────┘
                                      │  refined query
                                      ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 2. RETRIEVAL ENGINE — app/retrieval.py (Retriever, index built once)   │
   │    BM25Okapi over the approved KB corpus (k1=BM25_K1, b=BM25_B)        │
   │    _chunk_text(): document = question + " " + answer                   │
   │    score → filter (topic_tags / sensitivity) → top-K (RETRIEVAL_TOP_K) │
   │    KB = approved_answers.synthetic.json + kb/docs/*  (approved only)   │
   │    state: INTAKE → RETRIEVED                                           │
   └──────────────────────────────────────────────────────────────────────┘
                                      │  top-K RetrievedChunk[]
                                      ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 2b. ASSEMBLE CONTEXT — app/context_stack.py  (the "backpack", CTX1)    │
   │    4 layers = the ONLY thing the model sees:                           │
   │    Instruction · Retrieval([chunk_id] text) · Constraint · State       │
   │    (+ carries the original question)                                   │
   └──────────────────────────────────────────────────────────────────────┘
                                      │  ContextStack
                                      ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 3. DRAFT GENERATION + GROUNDING GATE                                   │
   │    llm.py LLMProvider.draft():                                         │
   │      • MockLLM   — offline, deterministic (DEFAULT / graded path)      │
   │      • ClaudeLLM — gated live lane (DRAFT_MODEL, temperature 0.0)      │
   │    draft.py grounding_check()  [RULE_GROUNDED_ONLY chokepoint]:        │
   │      (1) ≥ GROUNDING_MIN_CITATIONS citations                           │
   │      (2) every cited chunk_id ∈ retrieval layer (no fabrication)       │
   │      (3) content coverage ≥ GROUNDING_COVERAGE_MIN  (token overlap)    │
   │      (4) question coverage ≥ GROUNDING_QUESTION_COVERAGE_MIN           │
   │    FAIL → text replaced with UNGROUNDED_PLACEHOLDER + GROUNDING_FAIL   │
   │    state: RETRIEVED → DRAFTED                                          │
   └──────────────────────────────────────────────────────────────────────┘
                                      │  DraftAnswer (grounded | placeholder)
                                      ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 4. CONFIDENCE SCORING — app/confidence.py  (COMPUTED, not model-said)  │
   │    score = mean( coverage , grounded(1/0) , retrieval_dominance )      │
   │          = ( a + b + c ) / 3        ← equal-weight, no tuned weights   │
   │      coverage            = question tokens found in retrieved chunks   │
   │      grounded            = 1.0 if grounding gate passed else 0.0       │
   │      retrieval_dominance = top1/(top1+top2) BM25 ratio (npos≥2)        │
   │    band: ≥ CONFIDENCE_AUTO_THRESHOLD = auto ; else review              │
   │    LLM may write the rationale string only — never the number         │
   │    state: DRAFTED → SCORED                                             │
   └──────────────────────────────────────────────────────────────────────┘
                                      │  ConfidenceResult(score, rationale)
                                      ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 5. ROUTING ENGINE — app/routing.py  [RULE_HITM_REVIEW_TRIGGER]        │
   │    Precedence — FIRST match wins:                                      │
   │      [1] high-risk tag       → ROUTED_HIGH_RISK                        │
   │      [2] ambiguous retrieval → ROUTED_AMBIGUOUS  (top1−top2 < margin)  │
   │      [3] low confidence      → ROUTED_LOW_CONFIDENCE  (< review thr.)  │
   │      [4] sensitive chunk     → ROUTED_SENSITIVE  (internal/restricted) │
   │      [5] ungrounded draft    → ROUTED_UNGROUNDED  (lowest precedence)  │
   │    queue resolved from policy routing_map, else DEFAULT_REVIEWER_QUEUE │
   └──────────────────────────────────────────────────────────────────────┘
                  │  trigger fired                    │  no trigger
                  ▼                                   ▼
   ┌───────────────────────────────┐    ┌───────────────────────────────────┐
   │ state: SCORED →               │    │ state: stays at SCORED            │
   │        ROUTED_FOR_REVIEW      │    │ (confident draft; NOT auto-        │
   │ queue ∈ {security, legal,     │    │  approved — awaits a human)       │
   │ engineering, gtm, compliance} │    │                                   │
   │ REVIEW_BANNER on preview      │    │                                   │
   └───────────────────────────────┘    └───────────────────────────────────┘
                  │                                   │
                  └─────────────────┬─────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 6. HUMAN-IN-THE-LOOP — app/state.py  [RULE_NO_SELF_APPROVE]            │
   │    Hard stop: only actor="human" may reach REVIEW_APPROVED / APPROVED  │
   │    / EXPORTED; the agent attempting it raises SelfApproveBlocked.      │
   │    (Demo simulates the human action in scripts/run_demo.py.)           │
   │    state: ROUTED_FOR_REVIEW → REVIEW_APPROVED/REJECTED ;  SCORED →     │
   │           APPROVED  (human only)                                       │
   └──────────────────────────────────────────────────────────────────────┘
                                    │  APPROVED (human)
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │ 7. EXPORT — app/export.py  [RULE_NO_EXTERNAL_SEND + RULE_SENSITIVITY_GATE]
   │    APPROVED items only → Markdown + CSV to LOCAL DISK only             │
   │    internal/restricted held (SENSITIVITY_HOLD) unless review_approved  │
   │    affirmative audit: EXTERNAL_SEND_BLOCKED, destination=local_disk    │
   │    state: APPROVED → EXPORTED                                          │
   └──────────────────────────────────────────────────────────────────────┘

   ════════════════════════════════════════════════════════════════════════
   CROSS-CUTTING — app/audit.py  [RULE_AUDIT_COMPLETE]
     Every tool call AND every state transition above writes exactly one
     append-only JSONL AuditEvent (timestamp, ids, event, from/to state,
     rule, detail). redact() scrubs secrets/email/phone before write.
   ════════════════════════════════════════════════════════════════════════

   FAIL-SAFE — app/pipeline.py  [RULE_SAFE_TERMINAL]
     Any per-item exception → item lands in ROUTED_FOR_REVIEW with
     UNGROUNDED_PLACEHOLDER + an ERROR_TERMINAL audit event. No crash,
     no fabricated answer ever escapes run_pipeline().
```

---

## Module map (dependency order)

```
config.py    constants · RULE_* strings · lazy _get_claude()      [RULE_NO_SECRET]
schema.py    Pydantic models (QuestionnaireItem, DraftAnswer, AuditEvent, ...)
kb.py        load + validate KB / questionnaire / policy tags      [KB1 / DATA1]
retrieval.py BM25Okapi Retriever (build-once index)                [RET1..3]
query_optimizer.py  refine_query + strip_thinking_block (live)     [QREF*]
context_stack.py    4-layer backpack assembler                     [CTX1..4]
llm.py       LLMProvider → MockLLM (offline) / ClaudeLLM (live)    [DRAFT1/2]
draft.py     draft_answer + grounding_check                        [RULE_GROUNDED_ONLY]
confidence.py  deterministic score (mean of 3) + LLM rationale     [CONF1..3]
routing.py   5 review triggers (precedence)                        [RULE_HITM_REVIEW_TRIGGER]
state.py     state machine + no-self-approve guard                 [RULE_NO_SELF_APPROVE]
audit.py     append-only JSONL writer + redaction                  [RULE_AUDIT_COMPLETE]
export.py    Markdown+CSV, approved-only, sensitivity gate         [RULE_NO_EXTERNAL_SEND / _SENSITIVITY_GATE]
pipeline.py  end-to-end orchestration + fail-safe                  [RULE_SAFE_TERMINAL]
```

## Two LLM lanes behind one interface

```
                       ┌──────────────────────────┐
   code  ──draft()──►  │   LLMProvider (ABC)       │
                       └──────────────────────────┘
                            ▲                 ▲
              ┌─────────────┘                 └─────────────┐
       ┌──────────────┐                              ┌──────────────────┐
       │  MockLLM     │  offline, seeded,            │  ClaudeLLM       │  gated live lane;
       │  deterministic  the GRADED path             │  (Anthropic API) │  the ONLY outbound call
       └──────────────┘  (make test / make demo)     └──────────────────┘  (make demo-live)
```

## Item state machine (app/state.py)

```
INTAKE → RETRIEVED → DRAFTED → SCORED ─┬─► ROUTED_FOR_REVIEW ─► REVIEW_APPROVED ─► APPROVED ─► EXPORTED
                                       │          └──────────► REVIEW_REJECTED ─► (back to DRAFTED)
                                       └─────────────────────────────────────► APPROVED ─► EXPORTED
   agent may drive up to SCORED / ROUTED_FOR_REVIEW.
   APPROVED, EXPORTED, REVIEW_APPROVED, REVIEW_REJECTED = human-only (RULE_NO_SELF_APPROVE).
```
