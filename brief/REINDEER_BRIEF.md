# Comet — Reindeer RFP / Security-Questionnaire Response Agent
### Brief / Deck (for AEs · SEs · Security · Legal · GTM)

> Every number below references `FACTS.md` (the verified-facts ledger) — re-verify via its
> source-of-truth commands; this brief never restates a literal that lives there.

---

## The problem
Security questionnaires and RFP/RFI security sections are high-volume, repetitive, and high-stakes. A
wrong or unapproved answer to a question like *"Do you encrypt data at rest?"* is a compliance and trust
liability. Today the work is manual: someone hunts prior answers, drafts, and routes the sensitive ones
to Security/Legal by tribal knowledge. It is slow, inconsistent, and unauditable.

## What Comet does
Comet ingests a new questionnaire and, **per item**, runs a deterministic, human-gated pipeline:

```
intake → refine query → retrieve (grounded evidence) → assemble context →
draft → grounding-gate → score confidence → route the risky ones → track state →
audit every step → export (only human-APPROVED items, local disk only)
```

It drafts **only from a knowledge base of prior approved answers + product/security docs**, cites its
sources, scores its own confidence with deterministic rules, and **routes low-confidence or
policy-sensitive items to the right human reviewer**. It never sends anything outside the company and
**never self-approves** — a human makes the final call. The output is an auditable, exportable response
document.

## Why it's trustworthy — governance is in code, not prompts
Eleven boundaries are enforced as `RULE_*` constants, each with a single code chokepoint, an audit
reason-code, and a test that scans for it. The model cannot talk its way past them:
- **Grounded only** — no asserted answer without a cited retrieved chunk; otherwise the answer is
  replaced by a placeholder and routed for a human.
- **No self-approve** — only a human transitions an item to APPROVED/EXPORTED.
- **No external send** — export writes to local disk only, only for approved items.
- **Sensitivity gate** — internal/restricted content never reaches an export without human review.
- **Route the risky** — high-risk tag, ambiguous retrieval, low confidence, or sensitive content each
  forces human review.
- **Fail safe** — any component failure ends in a routed, audited terminal, never a crash or a
  fabricated answer.

## Architecture at a glance
- **Retrieval:** deterministic lexical `rank_bm25` over a synthetic KB (no embeddings, fully offline,
  reproducible). Recall@K is **measured**, not assumed (see `FACTS.md`).
- **Context Stack ("backpack"):** the only thing the model sees — four declared layers (Instruction /
  Retrieval / Constraint / State). This bounds both context dilution and hallucination.
- **Confidence is computed, not model-reported:** deterministic property validators (retrieval score,
  question coverage, grounding ratio) decide the number and the routing; the LLM may write only the
  rationale string.
- **Two LLM lanes behind one interface:** `MockLLM` (offline, seeded, deterministic — the graded path)
  and `ClaudeLLM` (gated live lane, the only outbound call). Swapping the vendor is a swap behind the
  interface.
- **Query refinement (Stage 10):** in the live lane the question is expanded into a better search query
  before retrieval; offline this is the identity, so the deterministic suite is byte-identical.

## Success metrics (all computed from labeled fixtures — see `FACTS.md`)
- **Recall@K = 1.0** on the held-out Recall gold (meets the `RECALL_AT_K_TARGET` bar).
- **Routing accuracy = 1.0**; **grounding match = 1.0**, with **raw_grounded = 0.833** — the eval
  deliberately includes a **known-ungrounded negative case** the gate must catch (it does), so the metric
  can actually go red. A green suite with no red case proves nothing.
- **Offline suite: 580 pass / 1 skip / 2 xfail** (current counts in `FACTS.md`), fully deterministic,
  network-free; the 1 skip is the live-gated error-path check and the 2 xfail document a known
  lexical-grounding limitation honestly.
- **Demo cases:** a confident auto-draft (exported after human approval) and a human-review exception
  (routed, banner-flagged, never auto-included).

## Business impact (qualitative — no production telemetry yet; see Assumptions)
- **Cycle time:** a grounded, cited first draft per item in seconds instead of a manual Drive hunt +
  copy-paste — the bottleneck moves from *finding* an answer to *approving* a draft.
- **GTM capacity:** AE/SE hours go back to selling; Security/Legal touch only the **routed** risky/sensitive
  minority, not every questionnaire.
- **Accuracy & compliance posture:** every exported answer is grounded in an approved KB chunk, cited, and
  audited — fewer wrong/unapproved answers and a defensible trail for Security/Legal.
- **Win rate (indirect):** faster, more consistent, more credible security responses remove a common
  late-stage deal blocker.
- *Quality is measured, not asserted — Recall@K / routing / grounding accuracy live in `FACTS.md`.*

## Human stays in control — and what must be true before rollout
The agent drafts, scores, and routes, but **never self-approves and never sends** — a named reviewer
approves before anything exports. Before an internal rollout, the following must hold:
- the KB is **curated and approval-gated** (only approved answers are retrievable);
- the **reviewer queues are staffed** (security / legal / engineering / gtm / compliance) with an agreed turnaround;
- **audit retention** is agreed with Security/Legal (the append-only JSONL is the system of record);
- an **accuracy / coverage bar** is accepted on the labeled eval; and
- the **live-citation-yield** mitigation is in place (uncited live drafts route to a human — see limitations).

## Build vs. buy
A thin, in-house agent beats a generic RFP SaaS here because the value *is* **governance**: code-enforced
guardrails, a complete audit trail, and a hard no-external-send boundary on Reindeer's own data — none of
which a black-box vendor can guarantee.

## Honest limitations (surfaced, not hidden)
- Grounding is **lexical** coverage, not semantic — backstopped by the live lane + human review.
- **Live grounding is materially lower than offline mock grounding** (characterized in
  `redteam/QA_AUDIT_50.md`): when the live model omits inline `[chunk_id]` citations the gate
  correctly forces human review rather than shipping an uncited claim. This is the safety property
  working as designed, not a regression. (It is also why the live draft prompt was changed to demand
  inline citations + answer-only output.)
- The KB is bounded synthetic data; production value scales with KB coverage.

## Assumptions
- KB, questionnaires, and policy tags are **synthetic** stand-ins for the real approved-answer corpus.
- Retrieval is **lexical** (`rank_bm25`); production may add semantic retrieval.
- Reviewers and queues exist and act on routed items; SLAs are organizational, not modeled here.
- Scope is the draft → route → audit loop; ticketing / e-sign / CRM integrations are out of scope by design.

## Future roadmap — the next automation after a successful rollout
1. **KB auto-curation:** turn newly *won* / approved answers into KB chunks automatically (a reviewer-feedback
   loop) so coverage compounds with every deal — the highest-leverage next step.
2. **Reviewer-feedback learning:** capture edits/approvals to tune confidence calibration and flag stale answers.
3. **Adjacent docs:** extend from questionnaires to MSAs / DPAs and the security sections of full RFPs.
4. **Integrations:** read questionnaires straight from Drive and push approved exports back — keeping the
   human-approval gate intact.

## What a 20-minute demo shows
1. `make demo` — both mandated cases end-to-end, offline, deterministic.
2. The audit log — one append-only event per transition, the spine of trust for Security/Legal.
3. A routed exception with the review banner, proving nothing sensitive auto-exports.
4. `make chat` — type your own question and watch the grounded, cited, routed answer in real time.
