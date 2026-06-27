# Brief — Stage 4: Confidence + routing + state machine

Read first (in order): `CLAUDE.md` → `PLAN.md` (Stage 4) → `QA_checklist.md` (`CONF1`–`CONF3`,
`ROUTE1`–`ROUTE3`, `STATUS1`–`STATUS2`) → `NOTES.md` (D-S4 + Structural insights), then this brief.

Goal: hybrid confidence (deterministic number + LLM-only rationale), the 3-trigger routing engine
(`RULE_HITM_REVIEW_TRIGGER`), and the item state machine with the `RULE_NO_SELF_APPROVE` guard.
Fully offline + deterministic.

## Scope — do ONLY this stage

### 0. `app/config.py` — NEW named constants (additions; PM is surfacing to Asaf — do NOT alter existing values)
- `DEFAULT_REVIEWER_QUEUE = "engineering"` — fallback queue when no topic tag maps (must ∈ `REVIEWER_QUEUES`).
- Materialize the §5.1 audit reason-codes this stage needs (string constants whose value == the name):
  `ROUTED_HIGH_RISK`, `ROUTED_AMBIGUOUS`, `ROUTED_LOW_CONFIDENCE`, `SELF_APPROVE_BLOCKED`.

### 1. `app/confidence.py` — hybrid confidence (graded contract; `CONF1`–`CONF3`)
```python
def score_confidence(
    chunks: list[RetrievedChunk],
    grounding: GroundingResult,
    question: str,
) -> ConfidenceResult:

def confidence_band(score: float) -> str:   # "auto" | "review"
```
- The **numerical `score` is computed ONLY from deterministic property validators** — the LLM never
  produces the number (`CONF1`). Use three bounded [0,1] validators and return their **equal-weight
  mean** (no weight constants):
  1. `coverage` — fraction of the question's significant tokens (reuse the tokenizer + stopword set
     pattern from `draft.py`/`retrieval.py`; do not duplicate — import or factor a shared helper if
     clean) present in the union of the retrieved chunk texts.
  2. `grounded` — `1.0` if `grounding.grounded` else `0.0`.
  3. `retrieval_dominance` — `top1/(top1+top2)` of the chunks' `bm25_score` (if ≥2 chunks and the sum
     > 0); `1.0` if exactly one positive-score chunk; `0.0` if no positive-score chunk.
- `ConfidenceResult.rationale` = a **deterministic template string** describing the three signals
  (offline). The LLM rationale is a documented live-lane extension — **do not build it now** (no dead
  code). `CONF2`: the score must be invariant to the rationale (compute it in a pure helper
  `_compute_score(...)`; a test proves changing/removing the rationale does not change `score`).
- `confidence_band` (`CONF3`): `score >= CONFIDENCE_AUTO_THRESHOLD` → `"auto"`;
  `score < CONFIDENCE_REVIEW_THRESHOLD` → `"review"`; **in-between → `"review"`** (conservative).
  Thresholds from §9 — no inline numbers.

### 2. `app/routing.py` — the routing engine (graded contract; `RULE_HITM_REVIEW_TRIGGER`; `ROUTE1`–`ROUTE3`)
```python
def route_for_review(
    item: QuestionnaireItem,
    chunks: list[RetrievedChunk],
    confidence: ConfidenceResult,
    policy_tags: dict,          # from app.kb.load_policy_tags()
) -> RoutingDecision:
```
Any one trigger fires → `should_route=True`. **Precedence (first match sets `reason_code` + `rule`):**
1. **High-risk tag** — `item.topic_tags ∩ HIGH_RISK_TAGS` (or `policy_tags["high_risk_tags"]`) →
   `reason_code = ROUTED_HIGH_RISK`; queue = `policy_tags["routing_map"]` for the matched high-risk tag.
2. **Ambiguity** — with ≥2 chunks, `top1_bm25 − top2_bm25 < AMBIGUITY_SCORE_MARGIN` (or conflicting
   chunks) → `reason_code = ROUTED_AMBIGUOUS`.
3. **Low confidence** — `confidence.score < CONFIDENCE_REVIEW_THRESHOLD` → `reason_code = ROUTED_LOW_CONFIDENCE`.
- For triggers 2/3, resolve `queue` from `policy_tags["routing_map"]` over the item's `topic_tags`
  (first mapped tag wins, deterministic order); fallback = `DEFAULT_REVIEWER_QUEUE`. **Queues are never
  hardcoded** — always from the policy map / the §9 default (`ROUTE3`).
- `rule = RULE_HITM_REVIEW_TRIGGER` whenever routed. No trigger → `RoutingDecision(should_route=False,
  queue=None, reason_code=None, rule=None)`.

### 3. `app/state.py` — state machine + `RULE_NO_SELF_APPROVE` (graded contract; `STATUS1`–`STATUS2`)
- `LEGAL_TRANSITIONS: dict[str, set[str]]` over `ITEM_STATES` (the happy path; example edges):
  INTAKE→{RETRIEVED}, RETRIEVED→{DRAFTED}, DRAFTED→{SCORED},
  SCORED→{ROUTED_FOR_REVIEW, APPROVED}, ROUTED_FOR_REVIEW→{REVIEW_APPROVED, REVIEW_REJECTED},
  REVIEW_APPROVED→{APPROVED}, REVIEW_REJECTED→{DRAFTED}, APPROVED→{EXPORTED}, EXPORTED→set().
- `HUMAN_ONLY_TARGETS = frozenset({REVIEW_APPROVED, REVIEW_REJECTED, APPROVED, EXPORTED})`.
- `class InvalidTransition(ValueError)` and `class SelfApproveBlocked(ValueError)` (the latter carries
  `reason_code = SELF_APPROVE_BLOCKED`).
- `def transition(current: str, target: str, *, actor: str = "agent") -> str:`
  1. `target ∉ LEGAL_TRANSITIONS.get(current, set())` → raise `InvalidTransition` (explicit message) — `STATUS1`.
  2. `target ∈ HUMAN_ONLY_TARGETS and actor != "human"` → raise `SelfApproveBlocked` carrying
     `SELF_APPROVE_BLOCKED` — **the agent can NEVER auto-transition into a review/approved/final state**
     (`RULE_NO_SELF_APPROVE`, `STATUS2`).
  3. else return `target`.

### 4. Tests (`CONF1`–`CONF3`, `ROUTE1`–`ROUTE3`, `STATUS1`–`STATUS2`) + progressive ENV4
- `CONF1` — score computed from validators only; identical inputs → identical score; no model call.
- `CONF2` — score invariant to the rationale (changing/removing rationale leaves score unchanged).
- `CONF3` — banding: `>= AUTO` → "auto"; `< REVIEW` → "review"; in-between → "review".
- `ROUTE1` — high-risk-tagged item routes with `ROUTED_HIGH_RISK` regardless of score; correct queue.
- `ROUTE2` — top1−top2 < `AMBIGUITY_SCORE_MARGIN` → `ROUTED_AMBIGUOUS`.
- `ROUTE3` — `score < CONFIDENCE_REVIEW_THRESHOLD` → `ROUTED_LOW_CONFIDENCE`; queue from the policy map
  (not hardcoded); a benign high-confidence non-high-risk item → `should_route=False`.
- `STATUS1` — legal edges allowed; an illegal edge raises `InvalidTransition`.
- `STATUS2` — agent→APPROVED/EXPORTED (and other human-only targets) raises `SelfApproveBlocked` with
  `SELF_APPROVE_BLOCKED`; the same transition by `actor="human"` is allowed.
- Add `app.confidence`, `app.routing`, `app.state` to the ENV4-progressive test (addition).

## QA checks to PASS (run, not inspect): `CONF1`–`CONF3`, `ROUTE1`–`ROUTE3`, `STATUS1`–`STATUS2` (+ `make test` green; `ENV4` clean)

## Constraints (from CLAUDE.md)
- **Confidence number is computed, never model-reported** (`CONF1`/`CONF2`) — the LLM may only ever
  touch the rationale string.
- Import-safe; deterministic; offline. No inline magic values — thresholds/queues from §9 / the policy map.
- No `data/*` value hardcoded in `app/` (`KB2`/`LEAK3`); queues come from the loaded policy map / §9 default.

## Do NOT
- Touch any spine file (PM-owned). Adding the NEW constants to `app/config.py` IS in scope; do NOT
  change any EXISTING §9 constant value, literal, schema field, or `RULE_*`.
- Change the `score_confidence` / `confidence_band` / `route_for_review` / `transition` signatures
  above — surface as DECISION-NEEDED.
- Implement audit, export, or the pipeline — Stages 5–6. (Routing/state just RETURN structured results;
  the audit emission of these reason-codes is wired in Stage 5.)
- Modify an existing graded test to make it pass (verifier-independence). Adding new tests / ENV4
  modules is fine. Do not commit. Do not edit Stage-1 `load_policy_tags`/its fixtures (use the §9
  `DEFAULT_REVIEWER_QUEUE` fallback instead of adding a data field).

## Deliver
Write `handbacks/stage-4.md` (CLAUDE §12.1 format). Report: `make test` pass/skip count, files
created/modified (call out the NEW config constants), each `CONF*`/`ROUTE*`/`STATUS*` ✅/⚠️
(test-verified), confirmation the confidence number is model-independent and the agent self-approve is
blocked, any DECISION-NEEDED, one next action. Return it as your final message. The PM re-runs the
checks, verifies score-determinism + self-approve-block independently, runs `/code-review`, records in `FACTS.md`.
