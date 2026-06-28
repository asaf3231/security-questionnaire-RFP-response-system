# Comet — Presentation Deck Plan (10 slides · 20 minutes)

> A slide-by-slide plan for the 20-minute walkthrough, followed by 20 minutes of technical Q&A.
> Each slide has: **ON SLIDE** (what to put on it), **SAY** (your spoken script), **DO** (live action),
> and a **TIME** budget. Total ≈ 20 min with a ~6-minute live demo in the middle.
>
> Codename: **Comet** — the Reindeer RFP / Security-Questionnaire Response Agent.

---

## Slide 1 — Title (1 min)

**ON SLIDE**
- **Comet** — an internal agent that drafts grounded, auditable answers to security questionnaires & RFPs
- "Governed automation: the model drafts, the code decides, a human approves."
- Your name · date

**SAY**
> "Hi, I'm [name]. I built Comet — an internal agent that takes a security questionnaire and produces a
> grounded, cited, auditable draft answer set, routing the risky items to the right human. The one idea
> I want you to leave with: the model writes language, but *code* makes every decision — so it's
> trustworthy by construction."

**TIME:** 1 min

---

## Slide 2 — The problem (2 min)

**ON SLIDE**
- Today: AEs & SEs get bespoke security/RFP/RFI docs from enterprise customers mid-deal
- Approved answers are scattered — Google Drive, past deals, product/security docs
- Manual = slow · inconsistent · **unauditable**
- A wrong/unapproved answer to "Do you encrypt at rest?" = a compliance & trust liability

**SAY**
> "Security questionnaires are high-volume, repetitive, and high-stakes. Today a salesperson hunts down
> prior answers across Drive and old deals, copy-pastes, and routes the sensitive ones to Security or
> Legal by tribal knowledge. It's slow, inconsistent, and — most importantly for a security workflow —
> there's no audit trail of *why* an answer went out. That last part is what makes it risky."

**TIME:** 2 min

---

## Slide 3 — What Comet does + the core idea (2.5 min)

**ON SLIDE**
- The per-item pipeline:
  ```
  intake → refine query → retrieve → assemble context →
  draft → grounding-gate → score confidence → route the risky →
  track state → audit every step → export (approved only, local disk)
  ```
- **Drafts only from approved KB answers + product docs** · cites sources · computes its own confidence
- **Never self-approves · never sends externally** — a human makes the final call
- **THE CORE IDEA: governance is enforced in code, not in prompts**

**SAY**
> "Comet runs this pipeline per question. It drafts *only* from a knowledge base of prior approved
> answers, it cites every source, it scores its own confidence with deterministic rules, and it routes
> low-confidence or policy-sensitive items to the right human. It never sends anything outside the
> company and never approves its own work. The thread through all of it: every guardrail is a Python
> chokepoint, not a polite request in a prompt. The model can't talk its way past an `if` statement."

**TIME:** 2.5 min

---

## Slide 4 — Architecture & the 3 key decisions (2 min)

**ON SLIDE**
- **Retrieval = `rank_bm25` (lexical), not embeddings** → deterministic, offline, reproducible
- **Confidence is COMPUTED in code, not model-reported** → 3 validators averaged
- **Two LLM lanes behind one interface** → `MockLLM` (offline, graded) · `ClaudeLLM` (gated live)
- The "backpack": the 4-layer Context Stack is the **only** thing the model sees

**SAY**
> "Three decisions define the design. One: retrieval is lexical BM25, not vector embeddings — so it's
> fully deterministic and reproducible, which is what lets us actually *measure* quality. Two: the
> confidence number is computed in pure Python from three signals; the model never grades its own work.
> Three: there's one LLM interface with two implementations — a deterministic mock for the graded
> offline path, and the gated Claude lane for live. And the model only ever sees four declared context
> layers — nothing else from the KB leaks in."

**TIME:** 2 min

---

## Slide 5 — Trust: the `RULE_*` guardrails (2 min)

**ON SLIDE**
- 11 boundaries, each = **one code chokepoint + one audit reason-code + one test**
- Grounded-only · No-self-approve · No-external-send · Sensitivity-gate · Route-the-risky · Fail-safe
- "A green test suite with no red case proves nothing" → eval includes a **known-bad case that must fail**

**SAY**
> "Trust comes from eleven `RULE_*` guardrails. Each one has a single place in the code that enforces
> it, an audit code it emits when it fires, and a test that scans for it. For example: no answer ships
> without a citation to a retrieved chunk; only a human reaches APPROVED; export is local-disk-only.
> And our eval deliberately includes a known-ungrounded item that the gate *must* catch — because a
> green suite with no red case proves nothing."

**TIME:** 2 min

---

## Slide 6 — LIVE DEMO (6 min) ★ the centerpiece

**ON SLIDE**
- `make demo` — two mandated cases, offline, deterministic
- Case 1: confident auto-draft → human-approved → exported
- Case 2: human-review exception → routed, banner-flagged → NOT exported
- Then: open the audit log

**DO (run live, in this order):**
1. `make demo` — narrate Case 1 (i1 confident 0.799 → approved → exported; i3 high score 0.880 but
   routed by its `security` tag — the defense-in-depth moment).
2. Narrate Case 2 (`case_review`): both items → `ROUTED_HIGH_RISK` → `legal`, banner shown, never exported.
3. `cat audit/q-review-001.jsonl` (or open it) — show one append-only line per step; point at a
   `ROUTED_HIGH_RISK` line and the `EXTERNAL_SEND_BLOCKED` / `destination=local_disk` export line.
4. (Optional, if time) `make chat` — type one question, watch a grounded/cited/routed answer live.

**SAY**
> "Let me run it. [run] Case 1 is the happy path — this item is grounded and confident, so after a
> simulated human approval it exports. Watch this one: it scores 0.88, very high — but it still routes,
> because it carries a `security` tag. We'd rather over-route to a human than ship an unreviewed
> security claim. Case 2 is the exception path: both items hit a high-risk legal tag, get routed to the
> legal queue with the review banner, and are never exported. Now the audit log — every step is one
> line: which rule fired, the routing decision, and the export confirming it stayed on local disk."

**TIME:** 6 min (this is the heart — practice the narration)

---

## Slide 7 — The brains: confidence → routing (2 min)

**ON SLIDE**
- **Confidence** = mean of 3 validators: question-coverage · grounded(1/0) · retrieval-dominance → [0,1]
- Bands: ≥0.75 auto · <0.50 forces review · in-between → review (conservative)
- **Routing** = 5 triggers, strict precedence: high-risk tag → ambiguous → low-confidence → sensitive → ungrounded
- Destination team is **data-driven** (policy `routing_map`): security / legal / engineering / gtm / compliance

**SAY**
> "The confidence number is three deterministic signals averaged: did we retrieve evidence about what
> was asked, did it pass the grounding gate, and how dominant was the top match. A low score forces
> human review. Routing is a strict precedence ladder of five triggers, and crucially the destination
> team isn't hardcoded — it's a config map from tag to team, so Reindeer edits one file to match its
> real org chart."

**TIME:** 2 min

---

## Slide 8 — How it fits Reindeer's stack (1.5 min)

**ON SLIDE**
- KB in ← nightly **Drive sync** feeds `load_kb()` (only approved chunks retrievable)
- Trigger ← questionnaire upload starts `run_pipeline()`
- Routing out → opens a **Slack/Jira** ticket for the real team
- SLAs + status updates ← the **audit log** (timestamped events) is the live feed a dashboard/SLA monitor consumes
- "We built the governed core + a clean seam at each edge; going live = wiring small adapters, no redesign"

**SAY**
> "In production, the core doesn't change — each edge is one small adapter. A nightly Drive sync feeds
> the knowledge base; a file upload triggers the pipeline; a routing decision opens a Slack or Jira
> ticket for the real team; and the audit log, which already timestamps every transition, is exactly the
> feed an SLA monitor and a status dashboard subscribe to. I built the hard part — the governed brain
> and the seams — so going live is integration, not a rebuild."

**TIME:** 1.5 min

---

## Slide 9 — Build · Debug · Explain + honest limits (2 min)

**ON SLIDE**
- **Build:** real service — schemas, state machine, audit log, pinned deps, one-command reproduce, 596 tests
- **Debug:** caught our *own* fabricated eval → rebuilt it falsifiable; debugged the live model from evidence (citations dropped → grounding tanked → fixed the prompt)
- **Explain:** every number traces to one ledger (`FACTS.md`) with a re-verify command; Brief for Legal, Appendix for engineers
- **Honest limits:** grounding is lexical (not semantic) · live grounding < offline (the safety gate working) · KB is synthetic

**SAY**
> "On building: this is a real service, not a notebook — typed schemas, a state machine, an audit log,
> pinned deps, a reproducible run. On debugging — my proudest catch was that an early version of our own
> eval was *fabricated*; I proved it, then rebuilt it to be falsifiable with a case that must go red. I
> also debugged the live model from evidence: it was dropping citations, which tanked grounding, so I
> changed the draft prompt. On explaining: every number traces to one ledger with a command to
> re-verify it. And I'm upfront about limits — grounding is lexical, live grounding is lower than offline
> *by design* because the gate forces review on uncited claims."

**TIME:** 2 min

---

## Slide 10 — Metrics, roadmap & close (1 min)

**ON SLIDE**
- **Measured** (all from labeled fixtures — `FACTS.md`): Recall@K = 1.0 · routing accuracy = 1.0 · grounding match = 1.0 with a real negative case · 596 offline tests, deterministic
- **Roadmap:** KB auto-curation from won deals → reviewer-feedback learning → semantic retrieval → Drive/Slack/Jira integrations
- **Close:** "Drafts in seconds, humans approve the risky few, every answer grounded + audited."

**SAY**
> "Everything is measured, not asserted — Recall@K, routing, and grounding are all computed from labeled
> fixtures and live in one ledger. The roadmap's highest-leverage step is auto-curating the KB from won
> deals so coverage compounds with every sale. The bottom line: a grounded, cited first draft in
> seconds, humans approving only the risky minority, and every answer grounded and auditable. Happy to
> go deep in Q&A."

**TIME:** 1 min

---

## Timing summary (≈ 20 min)
| Slide | Topic | Min |
|---|---|---|
| 1 | Title | 1.0 |
| 2 | Problem | 2.0 |
| 3 | What Comet does + core idea | 2.5 |
| 4 | Architecture · 3 decisions | 2.0 |
| 5 | Guardrails | 2.0 |
| 6 | **Live demo** | 6.0 |
| 7 | Confidence → routing | 2.0 |
| 8 | Fits the stack | 1.5 |
| 9 | Build/debug/explain + limits | 2.0 |
| 10 | Metrics · roadmap · close | 1.0 |
| | **Total** | **~22** (trim slide 3/9 to land at 20) |

## Demo safety checklist (do this BEFORE you present)
- [ ] `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- [ ] `make test` → green
- [ ] `make demo` → both cases run, exports written
- [ ] Have `audit/q-review-001.jsonl` open in a second window, ready to show
- [ ] Know your 3 strongest one-liners cold (core idea · defense-in-depth route · fabricated-eval debug)

## The 3 sentences to memorize
1. "The model writes language; the code makes every decision — governance is in code, not prompts."
2. "It scores 0.88 but still routes, because a high-risk tag overrides confidence — we over-route on purpose."
3. "My proudest debug was catching that our own eval was fabricated, and rebuilding it to be falsifiable."
