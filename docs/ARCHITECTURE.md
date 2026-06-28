# Comet — Architecture (code-accurate)

Reindeer RFP / Security-Questionnaire Response Agent. Constants live in `app/config.py`; numbers in `FACTS.md`.

## Pipeline (per item)

```
            ┌──────────────────────────────────────────────┐
            │   INPUT: data/questionnaires/*.synthetic.json │
            └──────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 1. INTAKE + QUERY REFINEMENT                                    │
   │    kb.load_questionnaire() → run_pipeline()  (state: INTAKE)    │
   │    query_optimizer.refine_query(): live=expand · offline=identity│
   └───────────────────────────────────────────────────────────────┘
                                  │  refined query
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 2. RETRIEVAL — app/retrieval.py                                 │
   │    BM25Okapi over approved KB → top-K       (INTAKE → RETRIEVED)│
   └───────────────────────────────────────────────────────────────┘
                                  │  top-K chunks
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 2b. ASSEMBLE CONTEXT — app/context_stack.py                     │
   │    4-layer "backpack" = the ONLY thing the model sees           │
   └───────────────────────────────────────────────────────────────┘
                                  │  ContextStack
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 3. DRAFT + GROUNDING GATE                                       │
   │    llm.py: MockLLM (default) / ClaudeLLM (live)                 │
   │    draft.py grounding_check  [RULE_GROUNDED_ONLY]:              │
   │      ≥1 citation · valid chunk_id · coverage≥0.5 · q-cov≥0.30   │
   │      FAIL → UNGROUNDED_PLACEHOLDER          (RETRIEVED → DRAFTED)│
   └───────────────────────────────────────────────────────────────┘
                                  │  DraftAnswer
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 4. CONFIDENCE SCORING — app/confidence.py                      │
   │    score = mean(coverage, grounded, retrieval_dominance)        │
   │          = (a + b + c) / 3   ·  computed, not model-reported    │
   │    band: ≥ auto-threshold = auto, else review  (DRAFTED→SCORED) │
   └───────────────────────────────────────────────────────────────┘
                                  │  ConfidenceResult
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 5. ROUTING — app/routing.py  [RULE_HITM_REVIEW_TRIGGER]        │
   │    first match wins:                                            │
   │    [1] high-risk tag  [2] ambiguity  [3] low-confidence         │
   │    [4] sensitive      [5] ungrounded                            │
   │    queue ← policy routing_map, else DEFAULT_REVIEWER_QUEUE      │
   └───────────────────────────────────────────────────────────────┘
                  │ routed                         │ no trigger
                  ▼                                ▼
   ┌──────────────────────────────┐   ┌──────────────────────────────┐
   │ SCORED → ROUTED_FOR_REVIEW   │   │ stays SCORED                 │
   │ queue: security/legal/eng/   │   │ (confident; never auto-      │
   │ gtm/compliance · banner      │   │  approved — awaits a human)  │
   └──────────────────────────────┘   └──────────────────────────────┘
                  │                                │
                  └────────────────┬───────────────┘
                                   ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 6. HUMAN-IN-THE-LOOP — app/state.py  [RULE_NO_SELF_APPROVE]    │
   │    only actor="human" reaches APPROVED  (demo: run_demo.py)     │
   └───────────────────────────────────────────────────────────────┘
                                   │  APPROVED (human)
                                   ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 7. EXPORT — app/export.py                                       │
   │    [RULE_NO_EXTERNAL_SEND + RULE_SENSITIVITY_GATE]              │
   │    APPROVED only → Markdown+CSV, local disk  (APPROVED→EXPORTED)│
   └───────────────────────────────────────────────────────────────┘

   ┌───────────────────────────────────────────────────────────────┐
   │ CROSS-CUTTING  audit.py [RULE_AUDIT_COMPLETE] — one append-only │
   │   JSONL event per step (secrets/PII redacted before write)      │
   │ FAIL-SAFE  pipeline.py [RULE_SAFE_TERMINAL] — any error →       │
   │   routed + ERROR_TERMINAL, never a crash or a fabricated answer │
   └───────────────────────────────────────────────────────────────┘
```

## Two LLM lanes, one interface

```
                    ┌────────────────────┐
   code ──draft()──►│  LLMProvider (ABC)  │
                    └────────────────────┘
                         │            │
              ┌──────────┘            └──────────┐
   ┌────────────────────┐          ┌──────────────────────┐
   │ MockLLM            │          │ ClaudeLLM            │
   │ offline · seeded   │          │ gated live lane —    │
   │ graded path        │          │ the only outbound    │
   │ (make test/demo)   │          │ call (make demo-live)│
   └────────────────────┘          └──────────────────────┘
```

## State machine (app/state.py)

```
INTAKE → RETRIEVED → DRAFTED → SCORED ─┬─► ROUTED_FOR_REVIEW → REVIEW_APPROVED → APPROVED → EXPORTED
                                       │            └────────► REVIEW_REJECTED → DRAFTED
                                       └──────────────────────────────────────► APPROVED → EXPORTED
human-only: REVIEW_APPROVED / REVIEW_REJECTED / APPROVED / EXPORTED  (RULE_NO_SELF_APPROVE)
```
