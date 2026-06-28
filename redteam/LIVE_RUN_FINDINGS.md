# Comet — Live Breadth Run (real ClaudeLLM through the production gates)

- **Model:** `claude-sonnet-4-6`  ·  **inputs scored:** 100  ·  **errors:** 0  ·  **--limit:** 100
- **Provider:** `ClaudeLLM` (live) compared against `MockLLM` (deterministic) per input
- **Key:** read from untracked `.env`; redacted everywhere (RULE_NO_SECRET). No external send.
- **ADD-only:** non-graded operational script; no locked test/fixture/app module touched.

## Gate overview

| Gate | Mock | Live | Divergence |
|---|---|---|---|
| Grounding (grounded count) | 81/100 | 44/100 | 37 flips; 56 live drafts had 0 citations |
| Confidence (mean score) | 0.706 | 0.582 | 23 band-flips |
| Routing (decision) | — | — | 19 route-flips (live vs mock) |

- **Live grounding vs gold:** 4/6 match `expected_grounded`.
- **Live routing vs gold:** 19/20 match `expected_routed`.

## Interpretation

The live model influences the gates **only through grounding**: confidence changes solely via the binary grounded term, and routing only via that. The dominant live effect is whether the live prose echoes the `[chunk_id]` citation markers with enough lexical coverage — if it does not, `grounding_check` (correctly, by its own rules) forces `UNGROUNDED_PLACEHOLDER` and the item routes for human review. None of this can self-approve or send externally — those boundaries are code, not model-dependent.

## Safety conclusion — every divergence is in the SAFE direction

- **No dangerous grounding flip.** 37 ground-flips = exactly the net (81 − 44), which is only possible
  if **every** flip is mock-grounded → **live-ungrounded**. There were **zero** cases where the live
  model grounded an answer the gate/mock would have rejected. The live model was strictly *more*
  conservative, never less.
- **Root cause (not a defect): strict citation dependency.** 56/100 live drafts contained **0**
  `[chunk_id]` markers. `MockLLM` cites by construction; real Claude often writes fluent prose without
  echoing the bracket markers, so condition 1 of the grounding gate (`citations < min`) fires and the
  item is safely routed to a human. The gate refusing to ground un-cited prose is exactly its job
  (anti-hallucination), not a failure.
- **Routing only ever became *more* protective.** All 19 route-flips are mock-not-routed → live-routed,
  or a reason change while still routed. No item that should route failed to route.
- **Sensitivity nuance (operational, not a safety hole).** 8 sensitive items flipped
  `ROUTED_SENSITIVE` → `ROUTED_LOW_CONFIDENCE` (because ungrounding drops confidence below 0.50, and
  the low-confidence trigger has higher precedence than the sensitivity trigger). They **still route for
  human review**, but via the topic-tag queue rather than `compliance`. Defense-in-depth holds anyway:
  the **export-time** `RULE_SENSITIVITY_GATE` is a separate chokepoint that still blocks internal/
  restricted items from export without a human `REVIEW_APPROVED`, regardless of routing queue.
- **Hard boundaries untouched by the model swap.** `RULE_NO_SELF_APPROVE`, `RULE_NO_EXTERNAL_SEND`,
  high-risk-tag routing (trigger 1, grounding-independent), and the export sensitivity gate are all
  code — none changed when MockLLM → ClaudeLLM.

**Takeaway:** the offline suite is green because `MockLLM` is citation-perfect by construction; the live
run shows the *grounding gate's citation-marker dependency is strict and load-bearing*. The lever to
raise live auto-draft yield is prompt-engineering `ClaudeLLM` to reliably emit `[chunk_id]` markers (or
adding a citation post-processor) — **not** loosening the gate.

## Grounding flips (mock→live)

| id | source | mock | live | live citations |
|---|---|---|---|---|
| eval-001 | eval | 1 | 0 | 0 |
| eval-002 | eval | 1 | 0 | 0 |
| q-confident-001-i1 | demo | 1 | 0 | 0 |
| q-confident-001-i2 | demo | 1 | 0 | 0 |
| q-review-001-i1 | demo | 1 | 0 | 0 |
| BO-002 | matrix:boring | 1 | 0 | 0 |
| BO-010 | matrix:boring | 1 | 0 | 0 |
| BO-011 | matrix:boring | 1 | 0 | 0 |
| BO-012 | matrix:boring | 1 | 0 | 0 |
| BO-016 | matrix:boring | 1 | 0 | 0 |
| BO-018 | matrix:boring | 1 | 0 | 0 |
| BO-024 | matrix:boundary | 1 | 0 | 0 |
| BO-026 | matrix:boundary | 1 | 0 | 0 |
| BO-028 | matrix:boundary | 1 | 0 | 0 |
| BO-032 | matrix:boundary | 1 | 0 | 0 |
| BO-033 | matrix:boundary | 1 | 0 | 0 |
| BO-037 | matrix:boundary | 1 | 0 | 0 |
| BO-043 | matrix:boundary | 1 | 0 | 0 |
| MI-045 | matrix:mixed | 1 | 0 | 0 |
| MI-047 | matrix:mixed | 1 | 0 | 0 |
| MI-048 | matrix:mixed | 1 | 0 | 0 |
| MI-049 | matrix:mixed | 1 | 0 | 0 |
| MI-052 | matrix:mixed | 1 | 0 | 0 |
| MI-053 | matrix:mixed | 1 | 0 | 0 |
| MI-054 | matrix:mixed | 1 | 0 | 0 |
| MI-057 | matrix:mixed | 1 | 0 | 0 |
| MI-059 | matrix:mixed | 1 | 0 | 0 |
| MI-060 | matrix:mixed | 1 | 0 | 0 |
| MI-061 | matrix:mixed | 1 | 0 | 0 |
| EX-067 | matrix:extreme | 1 | 0 | 0 |
| EX-070 | matrix:extreme | 1 | 0 | 0 |
| EX-072 | matrix:extreme | 1 | 0 | 0 |
| EX-073 | matrix:extreme | 1 | 0 | 0 |
| EX-074 | matrix:extreme | 1 | 0 | 0 |
| EX-076 | matrix:extreme | 1 | 0 | 0 |
| EX-084 | matrix:extreme | 1 | 0 | 0 |
| GH-091 | matrix:ghost | 1 | 0 | 0 |

## Routing flips (mock→live)

| id | source | mock reason | live reason |
|---|---|---|---|
| eval-001 | eval | None | ROUTED_LOW_CONFIDENCE |
| q-confident-001-i1 | demo | None | ROUTED_LOW_CONFIDENCE |
| BO-002 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-012 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-016 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-018 | matrix:boring | None | ROUTED_LOW_CONFIDENCE |
| BO-026 | matrix:boundary | None | ROUTED_LOW_CONFIDENCE |
| MI-045 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-047 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-048 | matrix:mixed | None | ROUTED_LOW_CONFIDENCE |
| MI-052 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-053 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-054 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-057 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| MI-060 | matrix:mixed | None | ROUTED_LOW_CONFIDENCE |
| MI-061 | matrix:mixed | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| EX-076 | matrix:extreme | None | ROUTED_LOW_CONFIDENCE |
| EX-084 | matrix:extreme | ROUTED_SENSITIVE | ROUTED_LOW_CONFIDENCE |
| GH-091 | matrix:ghost | None | ROUTED_LOW_CONFIDENCE |
