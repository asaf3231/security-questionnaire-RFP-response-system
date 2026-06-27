"""
app/state.py — Item state machine + RULE_NO_SELF_APPROVE guard (STATUS1–STATUS2).

Responsibility: define the legal state transitions for a questionnaire item and
enforce that only a human actor may transition an item into any human-only target
state.

The state machine:
  - LEGAL_TRANSITIONS maps each state to the set of valid next states.
  - HUMAN_ONLY_TARGETS is the frozenset of states that the agent may NEVER enter.
  - transition() is the single enforcement point for both rules.

RULE_NO_SELF_APPROVE enforced here (app/state.py) — the single chokepoint.
The audit reason-code SELF_APPROVE_BLOCKED is emitted (as the exception attribute)
when an agent attempts an illegal self-approve transition; the pipeline/audit layer
(Stage 5) logs it to the audit JSONL.

Import-safe: no side effects at import — no network, no .env, no data/* read, no
client constructed.
"""

from __future__ import annotations

from app.config import ITEM_STATES, RULE_NO_SELF_APPROVE, SELF_APPROVE_BLOCKED


# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------

class InvalidTransition(ValueError):
    """Raised when a requested state transition is not in LEGAL_TRANSITIONS.

    STATUS1 contract: items may only advance along legal edges; an illegal
    transition raises this exception rather than silently updating the state.
    """


class SelfApproveBlocked(ValueError):
    """Raised when the agent attempts to transition an item into a human-only state.

    STATUS2 / RULE_NO_SELF_APPROVE contract: the agent may NEVER transition an
    item into HUMAN_ONLY_TARGETS.  Only an explicit human action (actor="human")
    is permitted to make that transition.

    Attributes
    ----------
    reason_code : str
        Always SELF_APPROVE_BLOCKED (§5.1 audit reason-code).
    rule : str
        Always RULE_NO_SELF_APPROVE.
    """

    def __init__(self, current: str, target: str) -> None:
        self.reason_code: str = SELF_APPROVE_BLOCKED
        self.rule: str = RULE_NO_SELF_APPROVE
        super().__init__(
            f"RULE_NO_SELF_APPROVE violation: agent attempted to transition "
            f"'{current}' → '{target}', which is a human-only state. "
            f"Only actor='human' may perform this transition. "
            f"reason_code={self.reason_code}"
        )


# ---------------------------------------------------------------------------
# Legal transition graph (ITEM_STATES edges)
# ---------------------------------------------------------------------------

# Happy-path forward edges + the retry edge (REVIEW_REJECTED → DRAFTED).
# EXPORTED is a terminal state with no outgoing edges.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "INTAKE":            {"RETRIEVED"},
    "RETRIEVED":         {"DRAFTED"},
    "DRAFTED":           {"SCORED"},
    "SCORED":            {"ROUTED_FOR_REVIEW", "APPROVED"},
    "ROUTED_FOR_REVIEW": {"REVIEW_APPROVED", "REVIEW_REJECTED"},
    "REVIEW_APPROVED":   {"APPROVED"},
    "REVIEW_REJECTED":   {"DRAFTED"},
    "APPROVED":          {"EXPORTED"},
    "EXPORTED":          set(),
}

# Import-time invariant: every defined ITEM_STATE appears as a key.
assert set(LEGAL_TRANSITIONS.keys()) == set(ITEM_STATES), (
    "LEGAL_TRANSITIONS keys do not match ITEM_STATES — spine defect. "
    f"Missing: {set(ITEM_STATES) - set(LEGAL_TRANSITIONS.keys())}"
)

# ---------------------------------------------------------------------------
# Human-only target states (the self-approve guard)
# ---------------------------------------------------------------------------

# The agent may NEVER transition an item into any of these states.
# Only actor="human" is permitted to do so (RULE_NO_SELF_APPROVE).
HUMAN_ONLY_TARGETS: frozenset[str] = frozenset({
    "REVIEW_APPROVED",
    "REVIEW_REJECTED",
    "APPROVED",
    "EXPORTED",
})


# ---------------------------------------------------------------------------
# transition() — the graded contract (brief §3; STATUS1–STATUS2)
# ---------------------------------------------------------------------------

def transition(
    current: str,
    target: str,
    *,
    actor: str = "agent",
) -> str:
    """Advance an item from current to target, enforcing all state-machine rules.

    Rules (checked in order):
      1. target ∉ LEGAL_TRANSITIONS.get(current, set())
         → raise InvalidTransition (STATUS1)
      2. target ∈ HUMAN_ONLY_TARGETS and actor != "human"
         → raise SelfApproveBlocked (STATUS2, RULE_NO_SELF_APPROVE)
      3. Otherwise → return target (the new state).

    Parameters
    ----------
    current : str
        The item's current state (must be a value in ITEM_STATES).
    target : str
        The desired next state.
    actor : str
        Who is requesting the transition.  Defaults to "agent".
        Pass actor="human" only for genuine human-gate transitions.

    Returns
    -------
    str
        The new state string (== target) if the transition is legal.

    Raises
    ------
    InvalidTransition
        If the (current, target) edge is not in LEGAL_TRANSITIONS.
    SelfApproveBlocked
        If the agent attempts to enter a human-only target state.
    """
    # Rule 1: Legal edge check (STATUS1)
    allowed_targets = LEGAL_TRANSITIONS.get(current, set())
    if target not in allowed_targets:
        raise InvalidTransition(
            f"Illegal state transition: '{current}' → '{target}' is not a legal edge. "
            f"Legal targets from '{current}': {sorted(allowed_targets) or '(none — terminal state)'}."
        )

    # Rule 2: Human-only guard (STATUS2, RULE_NO_SELF_APPROVE)
    if target in HUMAN_ONLY_TARGETS and actor != "human":
        raise SelfApproveBlocked(current, target)

    # Rule 3: Legal and permitted — return the new state.
    return target
