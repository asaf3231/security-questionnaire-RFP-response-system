# fixtures/eval/PROVENANCE.md — Gold Case Provenance
#
# META-PROVENANCE (QA_checklist.md §15, RULE_METRIC_FALSIFIABLE)
#
# Every gold / expected-outcome entry in eval_cases.synthetic.json is derived here from
# the SPEC / INTENT — never from an observed output. This file is an ADD (respects
# RULE_GRADED_ARTIFACT_LOCK); the locked eval_cases.synthetic.json is not edited here.
#
# Format: Case ID → spec rationale → which rule/trigger drives the expectation.

---

## eval-001 — Confident auto-draft (POSITIVE case)

**Question:** "Does your platform encrypt data at rest, and if so, what encryption standard do you use?"
**Spec rationale:** The KB contains a strong, directly relevant approved chunk (kb-001) tagged `public`
covering AES-256 encryption at rest. The question's tokens appear in that chunk with high coverage.
No high-risk tag, no sensitivity trigger, and strong single-chunk retrieval dominance → confident
auto-draft path.
**Expected outcomes derive from:**
- `expected_routed = false` → RULE_HITM_REVIEW_TRIGGER: no trigger fires (no high-risk tag,
  retrieval is unambiguous, confidence ≥ CONFIDENCE_AUTO_THRESHOLD)
- `expected_grounded = true` → RULE_GROUNDED_ONLY: KB answer covers the question tokens
- `expected_queue = null`, `expected_reason = null` → no routing trigger fires
**Human gate still required before export** (RULE_NO_SELF_APPROVE) — confident ≠ auto-approved.

---

## eval-002 — High-risk tag routing to legal (POSITIVE routing case)

**Question:** "Do you carry cyber liability insurance?"
**Spec rationale:** The question topic tags include `legal`, which appears in HIGH_RISK_TAGS
(CLAUDE.md §9). Trigger 1 (high-risk tag) fires unconditionally — routing overrides confidence.
The KB has relevant coverage (compliance-related chunk), so grounding passes.
**Expected outcomes derive from:**
- `expected_routed = true` → RULE_HITM_REVIEW_TRIGGER trigger 1: `legal ∈ HIGH_RISK_TAGS`
- `expected_queue = "legal"` → policy_tags routing map: legal tag → legal queue
- `expected_reason = "ROUTED_HIGH_RISK"` → §5.1 RULE_HITM_REVIEW_TRIGGER reason-code
- `expected_grounded = true` → KB has relevant compliance coverage

---

## eval-003 — Dual high-risk tag (legal + security) → legal queue (POSITIVE routing case)

**Question:** "What indemnification provisions apply if a security breach originates from your platform?"
**Spec rationale:** Question carries BOTH `legal` and `security` topic tags. Both appear in
HIGH_RISK_TAGS. Trigger 1 (high-risk tag) fires; queue resolved via policy_tags routing_map
(legal takes precedence in the map). Question is deliberately rephrased from any KB chunk
(per RULE_NO_EVAL_CONTAMINATION note in the gold fixture) to avoid retrieval trivially finding
an identical string.
**Expected outcomes derive from:**
- `expected_routed = true` → RULE_HITM_REVIEW_TRIGGER trigger 1: `legal ∈ HIGH_RISK_TAGS`
- `expected_queue = "legal"` → policy_tags routing_map: legal + security → legal queue
- `expected_reason = "ROUTED_HIGH_RISK"` → §5.1 reason-code
- `expected_grounded = true` → KB retrieves relevant indemnification/security chunks

---

## eval-004 — Sensitivity trigger (Option A) → compliance (POSITIVE sensitivity routing case)

**Question:** "Is data in transit encrypted and what protocol versions are supported?"
**Spec rationale:** No high-risk tag (`encryption` + `infrastructure` + `network-security` are not
in HIGH_RISK_TAGS). Retrieval fetches kb-009 (tagged `internal`). Trigger 4 (sensitivity routing,
Option A, CLAUDE.md §5.1 RULE_HITM_REVIEW_TRIGGER row 4) fires: any retrieved chunk with
`internal`/`restricted` sensitivity → route to SENSITIVITY_REVIEW_QUEUE ("compliance").
Triggers 1–3 do not fire (no high-risk tag; retrieval is unambiguous; confidence ≥ threshold).
**Expected outcomes derive from:**
- `expected_routed = true` → RULE_HITM_REVIEW_TRIGGER trigger 4: retrieved kb-009 is `internal`
- `expected_queue = "compliance"` → SENSITIVITY_REVIEW_QUEUE = "compliance" (§9, Stage 7 Option A)
- `expected_reason = "ROUTED_SENSITIVE"` → §5.1 reason-code (Stage 7r)
- `expected_grounded = true` → KB has strong encryption/transit coverage

---

## eval-005 — Sensitivity trigger → compliance (SECOND positive sensitivity case, Option A)

**Question:** "What is your SOC 2 Type II certification status?"
**Spec rationale:** No high-risk tag. Retrieval fetches kb-010 (compliance doc, `internal`) and
kb-009 (`internal`). Two `internal`-tagged chunks in the retrieval set → trigger 4 fires.
Confirms Option A sensitivity routing holds across multiple internal-tagged chunks and a different
topic domain (certification vs. encryption).
**Expected outcomes derive from:**
- `expected_routed = true` → RULE_HITM_REVIEW_TRIGGER trigger 4: internal chunks retrieved
- `expected_queue = "compliance"` → SENSITIVITY_REVIEW_QUEUE (§9)
- `expected_reason = "ROUTED_SENSITIVE"` → §5.1 reason-code
- `expected_grounded = true` → KB has relevant SOC 2 coverage

---

## eval-006 — Weak/off-topic coverage → low confidence → routing (NEGATIVE / red case)

**Question:** "Can you provide a detailed breakdown of your quantum-resistant cryptographic roadmap?"
**Spec rationale (spec-first, not output-fitted):** The KB has NO approved chunk directly covering
quantum-resistant cryptography. The nearest chunk is kb-001 (AES-256 / encryption at rest —
wrong topic). This is INTENTIONALLY a coverage failure case:
1. Single positive chunk (`npos = 1`), so `retrieval_dominance = coverage` (not 1.0).
2. Question-coverage (`qcov`) of that chunk is ~0.111: "quantum-resistant cryptographic roadmap"
   tokens do not appear in kb-001's AES-256 answer → below GROUNDING_QUESTION_COVERAGE_MIN (0.30).
3. Grounding gate fails → `grounded = False`, answer replaced with UNGROUNDED_PLACEHOLDER.
4. Confidence = mean(coverage, grounded=0.0, retrieval_dominance=coverage) → well below
   CONFIDENCE_REVIEW_THRESHOLD (0.50) → ROUTED_LOW_CONFIDENCE.
**This is the required negative case (RULE_METRIC_FALSIFIABLE / META-FALSIFY):**
without it, the eval harness would have no case it is *required to score as failing/routing/rejecting*
— making it a tautology. This case was ESTABLISHED FROM SPEC INTENT (the KB genuinely lacks
quantum-crypto content) and was NOT edited to match observed output; the gold was set to
`expected_grounded=false` + `expected_routed=true` BEFORE the fix was implemented (Stage 7r
honest re-do; GOV-FAIL-S7 → 7r narrative in NOTES.md).
**Expected outcomes derive from:**
- `expected_grounded = false` → KB has no quantum-crypto coverage; qcov < GROUNDING_QUESTION_COVERAGE_MIN
- `expected_routed = true` → confidence < CONFIDENCE_REVIEW_THRESHOLD
- `expected_queue = "security"` → policy_tags routing_map: encryption tag → security queue
- `expected_reason = "ROUTED_LOW_CONFIDENCE"` → §5.1 reason-code

---

## recall_at_k_gold.json provenance

Each entry pairs a question (from the demo questionnaire) with its `relevant_chunk_ids` — the
approved KB chunk(s) that directly address it. Relevant chunks were identified by reading each
question and each KB chunk and determining whether the chunk's approved answer is on-topic and
factually responsive. No retrieval output was observed before assigning relevance; this is
a human-curated relevance judgment derived from question + chunk content, not from BM25 scores.
The retrieval Recall@K metric (EVAL1, RET2) is computed over this gold set by `app/eval/rubric.py`.
