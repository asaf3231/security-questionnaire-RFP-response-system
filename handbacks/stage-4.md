# Stage 4 Handback — Confidence + Routing + State Machine

**Executer:** cold SWE executer (general-purpose subagent)
**Date:** 2026-06-27
**Stage:** 4 — Confidence + routing + state machine
**Status at handback:** 🟡 Awaiting PM verification

---

## 1. What Changed

Stage 4 was found to be **already fully implemented** when the executer arrived.
All three modules (`app/confidence.py`, `app/routing.py`, `app/state.py`),
the new `app/config.py` constants, and the complete `tests/test_stage4.py` test file
were present and correct. No code was written or modified by this executer.

**Files verified (read, not modified):**
- `/app/config.py` — new Stage 4 constants confirmed present (see §1a below)
- `/app/confidence.py` — `score_confidence()`, `_compute_score()`, `confidence_band()` all present
- `/app/routing.py` — `route_for_review()` with three triggers + precedence present
- `/app/state.py` — `LEGAL_TRANSITIONS`, `HUMAN_ONLY_TARGETS`, `transition()`, `InvalidTransition`, `SelfApproveBlocked` all present
- `/tests/test_stage4.py` — 63 tests covering CONF1–CONF3, ROUTE1–ROUTE3, STATUS1–STATUS2, ENV4

### 1a. New `app/config.py` constants (Stage 4 additions — confirmed present)
| Constant | Value | Role |
|---|---|---|
| `ROUTED_HIGH_RISK` | `"ROUTED_HIGH_RISK"` | §5.1 audit reason-code, `app/routing.py` chokepoint |
| `ROUTED_AMBIGUOUS` | `"ROUTED_AMBIGUOUS"` | §5.1 audit reason-code, `app/routing.py` chokepoint |
| `ROUTED_LOW_CONFIDENCE` | `"ROUTED_LOW_CONFIDENCE"` | §5.1 audit reason-code, `app/routing.py` chokepoint |
| `SELF_APPROVE_BLOCKED` | `"SELF_APPROVE_BLOCKED"` | §5.1 audit reason-code, `app/state.py` chokepoint |
| `DEFAULT_REVIEWER_QUEUE` | `"engineering"` | Fallback queue; confirmed ∈ `REVIEWER_QUEUES` |

---

## 2. DoD Checklist

| QA ID | Check | Result |
|---|---|---|
| `CONF1` | Score computed from validators only; identical inputs → identical score; no model call | ✅ test-verified (7 tests pass) |
| `CONF2` | Score invariant to rationale; `_compute_score()` pure helper exported; changing/removing rationale does not change score | ✅ test-verified (4 tests pass) |
| `CONF3` | `confidence_band()` bands via §9 thresholds (no inline literals); in-between → "review" (conservative) | ✅ test-verified (8 tests pass) |
| `ROUTE1` | High-risk-tagged item routes with `ROUTED_HIGH_RISK` regardless of confidence; queue from policy map | ✅ test-verified (4 tests pass) |
| `ROUTE2` | top1−top2 < `AMBIGUITY_SCORE_MARGIN` → `ROUTED_AMBIGUOUS` | ✅ test-verified (4 tests pass) |
| `ROUTE3` | `score < CONFIDENCE_REVIEW_THRESHOLD` → `ROUTED_LOW_CONFIDENCE`; queue from policy map (not hardcoded); benign item → `should_route=False` | ✅ test-verified (7 tests pass) |
| `STATUS1` | Legal edges pass; illegal edge raises `InvalidTransition` (subclass of `ValueError`) | ✅ test-verified (10 tests pass) |
| `STATUS2` | Agent→human-only target raises `SelfApproveBlocked` with `reason_code=SELF_APPROVE_BLOCKED` and `rule=RULE_NO_SELF_APPROVE`; same transition by `actor="human"` allowed | ✅ test-verified (13 tests pass) |
| `ENV4` (progressive) | `app.confidence`, `app.routing`, `app.state` import cleanly with zero side effects; new config constants verified | ✅ test-verified (5 tests pass) |

---

## 3. QA Results

**Command:** `.venv/bin/python -m pytest tests/test_stage4.py -v`

**Stage 4 only:** 63 passed, 0 failed, 0 skipped in 0.34s

**Full suite:** `.venv/bin/python -m pytest -v`

**Full suite result:** 179 passed, 1 skipped in 0.77s

The 1 skip is `test_claude_llm_error_degrades_gracefully` in `tests/test_stage3.py` — the live-gated `DRAFT2` check that requires `ANTHROPIC_API_KEY`. This is correct and expected behavior (SKIPPED, never FAILED, per `QA_checklist.md`).

No regressions in Stages 1–3 tests.

---

## 4. Decisions Made

No new decisions made by this executer — Stage 4 was already implemented. The following design decisions from `NOTES.md` D-S4 were confirmed as implemented:

- Confidence score = equal-weight mean of three bounded [0,1] property validators (coverage, grounded, retrieval_dominance). No weight constants. **LLM never sets the number.**
- Routing precedence: high-risk tag → ambiguity → low-confidence (first match wins). Implemented in `app/routing.py`.
- `HUMAN_ONLY_TARGETS = frozenset({"REVIEW_APPROVED", "REVIEW_REJECTED", "APPROVED", "EXPORTED"})` — agent may never enter these states.
- `DEFAULT_REVIEWER_QUEUE = "engineering"` — fallback; confirmed ∈ `REVIEWER_QUEUES`.

---

## 5. DECISION-NEEDED

None. No graded-contract changes were required or made.

The `DEFAULT_REVIEWER_QUEUE = "engineering"` value is surfaced to Asaf per D-S4: retune if a different fallback queue is preferred.

---

## 6. Deviations / Risks

None. Stage 4 was already complete when the executer arrived. All contracts match the brief exactly:
- `score_confidence(chunks, grounding, question) -> ConfidenceResult` ✅
- `confidence_band(score) -> str` ✅
- `route_for_review(item, chunks, confidence, policy_tags) -> RoutingDecision` ✅
- `transition(current, target, *, actor="agent") -> str` ✅

No existing §9 constants were altered. No spine files touched. No Stage 5+ logic implemented. No commits made.

**Key contract confirmations:**
- **Confidence number is model-independent:** `_compute_score()` is a pure function with no LLM call; `test_score_uses_no_model_call` verifies `cfg._claude_client` remains `None` after `score_confidence()` returns.
- **Agent self-approve is blocked:** `transition(current, target_in_HUMAN_ONLY_TARGETS, actor="agent")` always raises `SelfApproveBlocked`; `transition(..., actor="human")` allows it. `test_default_actor_is_agent` confirms the default actor is "agent".

---

## 7. Next Recommended Action

Proceed to **Stage 5 — Audit log + export + hard boundary** (`app/audit.py`, `app/export.py`; QA IDs: `AUDIT1`–`AUDIT3`, `EXPORT1`–`EXPORT3`, `BOUND1`–`BOUND2`). The PM should first run `/code-review` on Stage 4's diff (thresholds, routing table, state machine, `RULE_HITM_REVIEW_TRIGGER`, `RULE_NO_SELF_APPROVE`) per the Stage 4 reviewer-gate requirement in `PLAN.md`, then update `STATE.md` and `FACTS.md` before spawning the Stage 5 executer.
