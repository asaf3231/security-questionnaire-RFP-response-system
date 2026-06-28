# Comet — Live Breadth Run (real ClaudeLLM through the production gates)

- **Model:** `claude-sonnet-4-6`  ·  **inputs scored:** 100  ·  **errors:** 0  ·  **--limit:** 100
- **Provider:** `ClaudeLLM` (live) compared against `MockLLM` (deterministic) per input
- **Key:** read from untracked `.env`; redacted everywhere (RULE_NO_SECRET). No external send.
- **ADD-only:** non-graded operational script; no locked test/fixture/app module touched.

## Gate overview

| Gate | Mock | Live | Divergence |
|---|---|---|---|
| Grounding (grounded count) | 81/100 | 25/100 | 56 flips; 75 live drafts had 0 citations |
| Confidence (mean score) | 0.706 | 0.519 | 44 band-flips |
| Routing (decision) | — | — | 18 route-flips (live vs mock) |

- **Live grounding vs gold:** 2/6 match `expected_grounded`.
- **Live routing vs gold:** 19/20 match `expected_routed`.

## Interpretation

The live model influences the gates **only through grounding**: confidence changes solely via the binary grounded term, and routing only via that. The dominant live effect is whether the live prose echoes the `[chunk_id]` citation markers with enough lexical coverage — if it does not, `grounding_check` (correctly, by its own rules) forces `UNGROUNDED_PLACEHOLDER` and the item routes for human review. None of this can self-approve or send externally — those boundaries are code, not model-dependent.

## Grounding flips (mock→live)

| id | source | mock | live | live citations |
|---|---|---|---|---|
| eval-001 | eval | 1 | 0 | 0 |
| eval-002 | eval | 1 | 0 | 0 |
| eval-003 | eval | 1 | 0 | 0 |
| eval-004 | eval | 1 | 0 | 0 |
| q-confident-001-i1 | demo | 1 | 0 | 0 |
| q-confident-001-i2 | demo | 1 | 0 | 0 |
| q-review-001-i1 | demo | 1 | 0 | 0 |
| q-review-001-i2 | demo | 1 | 0 | 0 |
| BO-003 | matrix:boring | 1 | 0 | 0 |
| BO-006 | matrix:boring | 1 | 0 | 0 |
| BO-008 | matrix:boring | 1 | 0 | 0 |
| BO-009 | matrix:boring | 1 | 0 | 0 |
| BO-010 | matrix:boring | 1 | 0 | 0 |
| BO-011 | matrix:boring | 1 | 0 | 0 |
| BO-013 | matrix:boring | 1 | 0 | 0 |
| BO-014 | matrix:boring | 1 | 0 | 0 |
| BO-015 | matrix:boring | 1 | 0 | 0 |
| BO-016 | matrix:boring | 1 | 0 | 0 |
| BO-019 | matrix:boring | 1 | 0 | 0 |
| BO-021 | matrix:boring | 1 | 0 | 0 |
| BO-022 | matrix:boring | 1 | 0 | 0 |
| BO-023 | matrix:boring | 1 | 0 | 0 |
| BO-024 | matrix:boundary | 1 | 0 | 0 |
| BO-026 | matrix:boundary | 1 | 0 | 0 |
| BO-029 | matrix:boundary | 1 | 0 | 0 |
| BO-032 | matrix:boundary | 1 | 0 | 0 |
| BO-035 | matrix:boundary | 1 | 0 | 0 |
| BO-037 | matrix:boundary | 1 | 0 | 0 |
| BO-038 | matrix:boundary | 1 | 0 | 0 |
| BO-042 | matrix:boundary | 1 | 0 | 0 |
| BO-043 | matrix:boundary | 1 | 0 | 0 |
| MI-044 | matrix:mixed | 1 | 0 | 0 |
| MI-045 | matrix:mixed | 1 | 0 | 0 |
| MI-046 | matrix:mixed | 1 | 0 | 0 |
| MI-047 | matrix:mixed | 1 | 0 | 0 |
| MI-048 | matrix:mixed | 1 | 0 | 0 |
| MI-050 | matrix:mixed | 1 | 0 | 0 |
| MI-051 | matrix:mixed | 1 | 0 | 0 |
| MI-053 | matrix:mixed | 1 | 0 | 0 |
| MI-055 | matrix:mixed | 1 | 0 | 0 |

## Routing flips (mock→live)

| id | source | mock reason | live reason |
|---|---|---|---|
| eval-001 | eval | None | ROUTED_LOW_CONFIDENCE |
| q-confident-001-i1 | demo | None | ROUTED_LOW_CONFIDENCE |
| BO-008 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-014 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-015 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-016 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-026 | matrix:boundary | None | ROUTED_LOW_CONFIDENCE |
| MI-045 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-047 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-048 | matrix:mixed | None | ROUTED_LOW_CONFIDENCE |
| MI-053 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-057 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-060 | matrix:mixed | None | ROUTED_LOW_CONFIDENCE |
| MI-061 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| EX-076 | matrix:extreme | None | ROUTED_LOW_CONFIDENCE |
| EX-081 | matrix:extreme | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| EX-084 | matrix:extreme | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| GH-091 | matrix:ghost | None | ROUTED_LOW_CONFIDENCE |
