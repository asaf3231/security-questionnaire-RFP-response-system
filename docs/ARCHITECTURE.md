# Comet — Architecture (code-accurate)

Reindeer RFP / Security-Questionnaire Response Agent. Constants live in `app/config.py`; numbers in `FACTS.md`.

## Pipeline (per item)

```
data/questionnaires/*.json
        │
        ▼
1. INTAKE + REFINE      kb.load_questionnaire() → run_pipeline() (state INTAKE)
                        query_optimizer.refine_query(): live=expand, offline=identity
        │
        ▼
2. RETRIEVE             retrieval.py — BM25Okapi over approved KB, top-K   [INTAKE→RETRIEVED]
        │
        ▼
2b. CONTEXT            context_stack.py — 4 layers = all the model sees
        │
        ▼
3. DRAFT + GROUNDING   llm.py: MockLLM (default) / ClaudeLLM (live)        [RETRIEVED→DRAFTED]
                        draft.py grounding_check [RULE_GROUNDED_ONLY]:
                          ≥1 citation · valid chunk_id · coverage≥0.5 · q-coverage≥0.30
                          FAIL → UNGROUNDED_PLACEHOLDER
        │
        ▼
4. CONFIDENCE          confidence.py — score = mean(coverage, grounded, dominance) = (a+b+c)/3
                        computed in code, never model-reported               [DRAFTED→SCORED]
        │
        ▼
5. ROUTING             routing.py [RULE_HITM_REVIEW_TRIGGER] first match wins:
                        [1] high-risk tag [2] ambiguity [3] low-confidence
                        [4] sensitive [5] ungrounded → queue from policy map
        │
   ┌────┴─────────────┐
   ▼ routed           ▼ no trigger
ROUTED_FOR_REVIEW   stays SCORED (awaits human; never auto-approved)
   └────┬─────────────┘
        ▼
6. HUMAN-IN-THE-LOOP   state.py [RULE_NO_SELF_APPROVE] — only actor="human" → APPROVED
        │
        ▼
7. EXPORT              export.py [RULE_NO_EXTERNAL_SEND + RULE_SENSITIVITY_GATE]
                        APPROVED only → Markdown+CSV, local disk only       [APPROVED→EXPORTED]

CROSS-CUTTING  audit.py [RULE_AUDIT_COMPLETE] — one append-only JSONL event per step (redacted)
FAIL-SAFE      pipeline.py [RULE_SAFE_TERMINAL] — any error → routed + ERROR_TERMINAL, no crash
```

## Two LLM lanes, one interface

```
code ─draft()─► LLMProvider (ABC)
                  ├─ MockLLM    offline, deterministic — graded path (make test/demo)
                  └─ ClaudeLLM  gated live lane — the only outbound call (make demo-live)
```

## State machine (app/state.py)

```
INTAKE → RETRIEVED → DRAFTED → SCORED ─┬─► ROUTED_FOR_REVIEW → REVIEW_APPROVED → APPROVED → EXPORTED
                                       │            └────────► REVIEW_REJECTED → DRAFTED
                                       └──────────────────────────────────────► APPROVED → EXPORTED
human-only: REVIEW_APPROVED / REVIEW_REJECTED / APPROVED / EXPORTED  (RULE_NO_SELF_APPROVE)
```
