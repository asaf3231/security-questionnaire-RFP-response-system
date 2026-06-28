# Comet — Live Breadth Run (real ClaudeLLM through the production gates)

- **Model:** `claude-sonnet-4-6`  ·  **inputs scored:** 50  ·  **errors:** 0  ·  **--limit:** 50
- **Provider:** `ClaudeLLM` (live) compared against `MockLLM` (deterministic) per input
- **Key:** read from untracked `.env`; redacted everywhere (RULE_NO_SECRET). No external send.
- **ADD-only:** non-graded operational script; no locked test/fixture/app module touched.

## Gate overview

| Gate | Mock | Live | Divergence |
|---|---|---|---|
| Grounding (grounded count) | 47/50 | 40/50 | 7 flips; 10 live drafts had 0 citations |
| Confidence (mean score) | 0.820 | 0.773 | 7 band-flips |
| Routing (decision) | — | — | 0 route-flips (live vs mock) |

- **Live grounding vs gold:** 5/6 match `expected_grounded`.
- **Live routing vs gold:** 11/11 match `expected_routed`.

## Interpretation

The live model influences the gates **only through grounding**: confidence changes solely via the binary grounded term, and routing only via that. The dominant live effect is whether the live prose echoes the `[chunk_id]` citation markers with enough lexical coverage — if it does not, `grounding_check` (correctly, by its own rules) forces `UNGROUNDED_PLACEHOLDER` and the item routes for human review. None of this can self-approve or send externally — those boundaries are code, not model-dependent.

## Grounding flips (mock→live)

| id | source | mock | live | live citations |
|---|---|---|---|---|
| eval-003 | eval | 1 | 0 | 0 |
| q-review-001-i1 | demo | 1 | 0 | 0 |
| q-review-001-i2 | demo | 1 | 0 | 0 |
| BO-019 | matrix:boring | 1 | 0 | 0 |
| BO-021 | matrix:boring | 1 | 0 | 0 |
| BO-022 | matrix:boring | 1 | 0 | 0 |
| BO-035 | matrix:boundary | 1 | 0 | 0 |
