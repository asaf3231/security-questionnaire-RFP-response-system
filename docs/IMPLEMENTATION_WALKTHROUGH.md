# Comet — Implementation Walkthrough (Presentation Q&A)

**Codename:** Comet — the Reindeer RFP / Security-Questionnaire Response Agent
**Purpose of this document:** a presentation-ready, English-language walkthrough that answers the
seven core questions about *how the agent flow was actually implemented in code*. Each section maps
the assignment requirement → the design decision → the exact code chokepoint (with `file:line`
references) so you can demo it live and defend it under questioning.

> **The one idea behind everything:** *governance is enforced in code, not in prompts.* Every boundary
> is a `RULE_*` constant in `app/config.py` with (1) a single code chokepoint that enforces it, (2) an
> audit reason-code emitted when it fires, and (3) a test ID that scans for it. The model cannot talk
> its way past a Python `if` statement.

**The end-to-end agent flow (one item):**

```
INTAKE → refine_query → retrieve → assemble_context →
draft_answer + grounding_check → score_confidence → route_for_review →
(route to a human  OR  await human approval) → human APPROVED → export (local disk only)
```

Every state transition and every tool call writes exactly one append-only audit event.

---

## 1. Intake — How a new questionnaire is received (Trigger / Input)

### What the assignment asks
The system must detect a **Trigger/Input** that is *a new security questionnaire*. Organizational
context: today AEs (Account Executives) and SEs (Sales Engineers) receive **bespoke** security / RFP /
RFI documents from enterprise customers during the sales cycle. The demo must show the **starting point
of the agent flow** the moment it receives or "initiates" the new questionnaire and hands it to the
processing stages.

### How it is implemented
The input is a **structured questionnaire record — not a chat**. It is a list of items, each item a
question with an ID and optional topic tags. There is deliberately **no network server / no webhook**
(by design — see `RULE_NO_EXTERNAL_SEND`); the agent is *initiated* over a CLI entry point.

**Trigger / entry points:**
- `make demo` → `scripts/run_demo.py` — runs the full flow on the two demo questionnaires offline.
- `make chat` → `scripts/run_chat.py` — an interactive REPL: type one question, watch the flow run.
- `scripts/run_questionnaire.py` — run an arbitrary questionnaire file (offline or `--live`).

**Input shape** (synthetic stand-in for the real corpus scattered across Drive / past deals):
`data/questionnaires/*.synthetic.json`, e.g.:

```json
{
  "questionnaire_id": "q-confident-001",
  "items": [
    {
      "item_id": "q-confident-001-i1",
      "question": "Does your platform encrypt data at rest, and if so, what encryption standard do you use?",
      "topic_tags": ["encryption", "infrastructure", "data-handling"]
    }
  ]
}
```

**Validation on intake — a malformed input is a clean startup error, never a crash.**
`load_questionnaire()` (`app/kb.py:148`) enforces:
- `questionnaire_id` and `items` must be present → explicit `ValueError` (not a `KeyError`).
- every item must have `item_id` + `question`; further validation is delegated to the Pydantic model
  `QuestionnaireItem` (`app/schema.py:22`), whose `must_be_nonempty` validator rejects empty strings.
- `topic_tags` is optional (defaults to `[]`).

**The first step of the agent flow** (`app/pipeline.py:180` onward, inside `run_pipeline`):
each item starts in state `INTAKE` and **immediately writes its first audit event** before any
processing — a `tool_call` event with `{"tool": "intake", "question": ...}` (`app/pipeline.py:187`).
The item then advances *only* through the state machine (`ITEM_STATES` in `app/config.py:101`).

### What to show in the demo
Run `make demo`; point at the `DEMO CASE` header printed by `run_case()` (`scripts/run_demo.py:86`),
then open the audit log `audit/q-confident-001.jsonl` and show the very first line — the `intake`
event. That line *is* the agent "initiating" on the new questionnaire.

### Defensible talking point
> "We accept a structured, validated document and reject a malformed one at the boundary — bad input
> never reaches the agent's logic. The flow's true starting point is the first audit event, so even
> intake is on the auditable record."

---

## 2. Retrieval — Pulling prior answers + product/security docs from the Knowledge Base

### What the assignment asks
The system must perform **knowledge-base retrieval** — and this is one of the ≥3 required system
interactions: **retrieving prior Q&A** from the knowledge base. The approved organizational knowledge
today lives scattered across **Google Drive, past deals, and official product/security docs**. The
demo must show the agent reaching those sources (real or **mocked**) and pulling **prior approved
answers** to ground the current response.

### How it is implemented
**Technology choice: deterministic lexical retrieval with `rank_bm25` (BM25Okapi) — not embeddings.**
This is a conscious decision: fully offline, reproducible run-to-run, no vector DB, no API cost. The
library is used directly (we do not hand-roll BM25). See `app/retrieval.py`.

**The Knowledge Base = two sources unified into one corpus** (`load_kb()`, `app/kb.py:46`):
1. `data/kb/approved_answers.synthetic.json` — **prior approved Q&A** (the "won deals / past answers").
2. `data/kb/docs/*.synthetic.json` — **product / security documents** (e.g. a security overview).

This models the real "scattered sources" requirement: prior Q&A *and* formal docs feed one retrieval
index. Each chunk carries:
`chunk_id, question, answer, source, sensitivity, topic_tags[], approved`.

**Hard KB invariants (enforced at load, `KB1`):**
- Required fields (`chunk_id`, `answer`, `sensitivity`) must be present and non-empty → `ValueError`.
- `sensitivity` must be one of `SENSITIVITY_TAGS` (`public` / `internal` / `restricted`).
- `chunk_id` must be **unique** across both sources (collision → `ValueError`).
- **Only `approved == True` chunks are ever retrievable** — unapproved answers are loaded but filtered
  out at indexing time (`app/retrieval.py:99`). This is the "prior *approved* answers" guarantee.

**The retrieval engine** (`Retriever` class, `app/retrieval.py:76`):
1. **Index built once** in `__init__` over the full approved corpus (standard RAG pattern → stable
   corpus-level IDF). The pipeline builds one `Retriever` and reuses it for every item
   (`app/pipeline.py:167`).
2. **Deterministic tokenizer** (`_tokenize`, `app/retrieval.py:52`): lowercase + split on
   non-alphanumeric runs. No stemming, no environment-dependent stopword list → identical output for
   identical input (this is what makes `RET3`/determinism hold).
3. **Document text** per chunk = `question + " " + answer` (or `answer` alone) — so BM25 sees both the
   prior question and its approved answer (`_chunk_text`, `app/retrieval.py:61`).
4. **Score, then filter, then top-K** (`retrieve()`, `app/retrieval.py:107`):
   - `BM25Okapi.get_scores()` scores the query against the full corpus (params `BM25_K1`, `BM25_B`).
   - filters are applied *after* scoring: `topic_tags` (keep chunks sharing ≥1 tag) and optional
     `allowed_sensitivities`.
   - sort by score **descending**, with `chunk_id` ascending as a deterministic tiebreak; return the
     top `RETRIEVAL_TOP_K` (=5).

**Where retrieval sits in the flow** (`app/pipeline.py:228`): the refined query is scored against the
corpus, the result is audited (`tool_call`, `tool=retrieve`, with `n_chunks` + `chunk_ids`), and the
item transitions `INTAKE → RETRIEVED`.

**Mocked vs. real:** the KB files are local synthetic stand-ins (the "mocked API" for Drive / past
deals). The *retrieval algorithm itself is real* — swapping the synthetic JSON for a real exported
corpus needs no code change.

### Concrete example
For item i1 ("Does your platform encrypt data at rest…?") with tags `["encryption", …]`, BM25 ranks
`kb-001` first — the prior approved answer *"All customer data is encrypted at rest using AES-256…"*
(`data/kb/approved_answers.synthetic.json:3`). That chunk becomes the evidence the draft is built from.

### Defensible talking point
> "Retrieval is deterministic and offline, so the eval is reproducible and we *measure* quality rather
> than assume it — Recall@K = 1.0 on the held-out gold (in `FACTS.md`). Only approved chunks are
> retrievable, so the agent can only ground on what a human already blessed."

---

## 3. Draft Generation — How the answer draft is composed

### What the assignment asks
The agent owns **draft generation** — its goal is to **draft safe responses**, grounded directly in
the retrieved KB evidence (prior approved answers + product docs). The code must show a **prompt /
tool-call pattern** and a clear **structured output / schema** showing how the LLM processes the
question + retrieved evidence into a well-formed answer with structured argumentation.

### How it is implemented

**Step A — assemble the Context Stack ("the backpack").** Before any model call, we build the
**only** context the model is allowed to see (`assemble_context`, `app/context_stack.py:80`). This is a
4-layer structured object (`ContextStack`, `app/schema.py:54`):

| Layer | Content | Code |
|---|---|---|
| **Instruction** | persona + the 5 RFP-handling rules ("answer ONLY from the Retrieval Context", "cite every chunk", "do not invent") | `INSTRUCTION_CONTEXT`, `app/context_stack.py:29` |
| **Retrieval** | ONLY the passed-in chunks, each as `[chunk_id] text` — nothing else from the KB reaches the model | `app/context_stack.py:111` |
| **Constraint** | the base hard boundary; for **high-risk** items a stricter clause is injected ("do not assert a legal/compliance/security position without a directly supporting chunk; defer to human review") | `app/context_stack.py:113` |
| **State** | "Question X of Y", item ID, current pipeline state | `app/context_stack.py:118` |
| (carried) `question` | the **original** questionnaire question, so the live model answers the actual question rather than reverse-engineering it from chunks (Stage 10 addition) | `app/context_stack.py:130` |

This is the `CTX1` guarantee: *the backpack is the only context the model sees.* It bounds both context
dilution and hallucination structurally.

**Step B — the LLM interface (one exit to a model).** All model access goes through one abstract
interface, `LLMProvider.draft(context_stack) -> DraftAnswer` (`app/llm.py:81`). Two implementations sit
behind it (vendor is a swap behind the interface):
- **`MockLLM`** (`app/llm.py:172`) — offline, deterministic, seeded. **The graded path** for all tests
  and `make demo`. It synthesizes a grounded answer by joining the retrieval entries and citing every
  `chunk_id` it used — so the offline path is grounded-by-construction and reproducible.
- **`ClaudeLLM`** (`app/llm.py:217`) — the gated live lane (`make demo-live`), the only outbound call
  in the whole system. The Anthropic client is a lazy singleton (`config._get_claude()`,
  `app/config.py:160`) — never built at import time.

**The prompt pattern** (`ClaudeLLM._build_prompt`, `app/llm.py`): the prompt is built **only** from the
ContextStack, in a fixed order — `INSTRUCTIONS → QUESTION → RETRIEVAL CONTEXT → CONSTRAINTS → STATE →
TASK`. The TASK block tells the model to answer only from the Retrieval Context and to cite the chunks
it used (with a one-shot example), and "if the context doesn't address the question, say so and don't
invent a citation."

**The tool-call pattern — `submit_answer` (live lane, structured citations).** In the live lane the
draft call uses Anthropic's native **tool use / function calling**: it passes a `submit_answer` tool
whose `input_schema` makes `answer` **and** `citations` (an array of chunk_ids) *required* fields, and
forces the model to use it via `tool_choice={"type":"tool","name":"submit_answer"}`
(`_SUBMIT_ANSWER_TOOL`, `app/llm.py`). So citations are a **schema-required field**, not regex-scraped
from prose — this removes the intermittent "cit=0" failure where the model dropped its inline
`[chunk_id]` markers and the grounding gate then (correctly) rejected a covered answer. The tool result
is read from the `tool_use` block (`_extract_tool_answer`); a text-only response falls back to the prose
path (backward-compatible).

**Structured output / schema.** Whichever path produced the answer, it is normalized into a typed
Pydantic structure, never a free string:
- `DraftAnswer { text: str, citations: list[Citation] }` (`app/schema.py:87`) — `text` must be
  non-empty (validator), and `citations` is a list of `Citation { chunk_id, source }`
  (`app/schema.py:80`).
- citations are **validated against the retrieval layer** — model-claimed ids that weren't retrieved are
  dropped (no fabrication), de-duplicated, and any inline `[chunk_id]` markers the model also wrote into
  the answer text are recovered as a union (`_known_chunk_ids` + `_parse_citations`, `app/llm.py`).
- empty / malformed tool input degrades to `UNGROUNDED_PLACEHOLDER` (`DRAFT2`).

(Live evidence drove this design: a prior `<thinking>` scaffold suppressed inline citations and tanked
live grounding; the `submit_answer` tool then made citations structural rather than prose-scraped — see
`FACTS.md`.)

**Step C — the grounding gate (this is what makes it a *safe* response).** Right after drafting, every
draft passes through `grounding_check()` — the single chokepoint for `RULE_GROUNDED_ONLY`
(`app/draft.py:156`). A draft is rejected as **ungrounded** if ANY of:
1. fewer than `GROUNDING_MIN_CITATIONS` (=1) citations;
2. any cited `chunk_id` is not in the retrieval layer (fabricated/unretrieved);
3. content coverage `< GROUNDING_COVERAGE_MIN` (=0.5) — i.e. less than half of the draft's significant
   tokens appear in the cited chunks (catches text not supported by the evidence);
4. (when the question is supplied) question coverage `< GROUNDING_QUESTION_COVERAGE_MIN` (=0.30) — the
   cited chunks don't actually address the question.

If rejected, the answer is replaced **byte-exactly** with
`UNGROUNDED_PLACEHOLDER = "[NO GROUNDED ANSWER FOUND — ROUTED FOR HUMAN INPUT]"` and the audit
reason-code `GROUNDING_FAIL` is emitted. **No fabricated answer is ever asserted.**

**Orchestration** (`draft_answer`, `app/draft.py:244`): resolve provider (default `MockLLM`) → call
`provider.draft()` (any provider error degrades to the placeholder, `DRAFT2`) → run `grounding_check`
→ return the grounded answer (or the placeholder). In the pipeline this is `app/pipeline.py:307`.

### What to show in the demo
Show `ContextStack` being assembled, the `_build_prompt` TASK block (the citation contract), and the
`DraftAnswer` schema. Then show the grounding gate replacing an uncited draft with the placeholder.

### Defensible talking point
> "The model only ever sees four declared layers, and its output must be cited and structured. If it
> doesn't cite, or cites something it wasn't given, code — not a prompt — replaces the answer with a
> placeholder and routes it to a human. 'Safe response' is a property the code guarantees."

---

## 4. Confidence Scoring — How the answer's confidence is computed

### What the assignment asks
An explicit core requirement: **confidence scoring**. The agent must **flag low-confidence items**.
The score acts as a **router**: high → proceed toward a confident auto-draft; low → an **exception**
needing human intervention. Show the logic that defines the score, how it's represented in the schema,
and how it drives the routing decision.

### How it is implemented — the score is COMPUTED, never model-reported
This is the most important design point and a strong talking point: **the LLM never produces the
confidence number.** It is a deterministic function of three property validators
(`_compute_components`, `app/confidence.py:78`). The LLM may write only the *rationale string*
(explanatory), which by construction cannot affect the number (`CONF2`).

The score is the **equal-weight mean of three bounded [0,1] validators**:

1. **coverage** — fraction of the *question's* significant tokens (minus stopwords) that appear in the
   union of the retrieved chunk texts. "Did we even retrieve evidence about what was asked?"
   (`app/confidence.py:91`).
2. **grounded** — `1.0` if the grounding gate passed, else `0.0` (`app/confidence.py:104`). This wires
   the grounding gate (Q3) directly into the number.
3. **retrieval_dominance** — how decisively the top chunk wins (`app/confidence.py:106`):
   - ≥2 positive-score chunks → `top1 / (top1 + top2)`;
   - exactly 1 positive chunk → `= coverage` (no unearned corroboration bonus for a weak single-chunk
     answer — the Stage-7r fix);
   - 0 positive chunks → `0.0`.

```python
score = (coverage + grounded_val + retrieval_dominance) / 3.0   # app/confidence.py:127
```

The function is **pure** — no I/O, no randomness, no model call — so identical inputs give an identical
score (`CONF1`). `_compute_components` is the single source of truth, reused for both the number and the
rationale so they can never drift (`app/confidence.py:211`).

**Schema representation** — `ConfidenceResult { score: float [0,1], rationale: str }`
(`app/schema.py:105`). The Pydantic constraint `Field(ge=0.0, le=1.0)` bounds the score; the comment in
the model states explicitly that `rationale` "does NOT affect the score or routing."

**The rationale string** (`score_confidence`, `app/confidence.py:173`) is a deterministic offline
template built from the exact component values, e.g.:
`"Confidence 0.799 = mean(coverage=0.625, grounded=1.0, retrieval_dominance=0.771). Retrieved 5
chunk(s); top BM25 score …; grounding gate: PASS."`

**Banding → routing input** (`confidence_band`, `app/confidence.py:236`), thresholds from `config.py`:
- `score >= CONFIDENCE_AUTO_THRESHOLD` (=0.75) → `"auto"` (eligible for a confident auto-draft);
- otherwise → `"review"` — note this is **conservative**: an in-between score (0.50–0.75) also bands to
  "review," not "auto."

**How it drives the decision** — the *hard* routing trigger uses the raw number, not the band:
`route_for_review` routes when `confidence.score < CONFIDENCE_REVIEW_THRESHOLD` (=0.50) with reason-code
`ROUTED_LOW_CONFIDENCE` (`app/routing.py:166`). So a low score *flags the item and forces human review*
— exactly the "low-confidence → exception" requirement.

### Worked numbers (from `make demo`, in `FACTS.md`)
- i1 (encrypt at rest) → **0.799** → band `auto`, not routed → eligible for human approval → exported.
- i3 (MFA) → **0.880** → high score, but still routed (its `security` high-risk tag overrides — see Q5;
  this is the "defense-in-depth" showcase).
- eval-006 (negative case) → **0.074** < 0.50 → `ROUTED_LOW_CONFIDENCE` — the gate catching a weak item.

### Defensible talking point
> "We never trust the model to grade its own homework. Confidence is three deterministic signals —
> question coverage, the grounding gate, and retrieval dominance — averaged in pure Python. The model
> only writes a human-readable rationale. The number is reproducible and falsifiable: our eval includes
> a known-bad item (0.074) that *must* score low, so the metric can actually go red."

---

## 5. Reviewer Routing — When and how an item is routed to a human

### What the assignment asks
Human routing fires in two main cases: **low-confidence** items and **policy-sensitive** items
(simulating a check of policy / sensitivity tags). Exceptions must route to the **right team —
Security, Legal, or Engineering** — by the nature of the question. Show an explicit **exception path**:
how an item gets stuck, tagged, and routed to the appropriate human reviewer.

### How it is implemented — one chokepoint, five triggers in strict precedence
`route_for_review()` (`app/routing.py:90`) is the single chokepoint for `RULE_HITM_REVIEW_TRIGGER`. The
**first** matching trigger wins (precedence matters — it sets the reason-code):

| # | Trigger | Condition | Reason-code | Code |
|---|---|---|---|---|
| 1 | **High-risk tag** | item has a tag in `HIGH_RISK_TAGS` (`legal`, `security`) | `ROUTED_HIGH_RISK` | `app/routing.py:140` |
| 2 | **Ambiguous retrieval** | `top1 − top2` BM25 gap `< AMBIGUITY_SCORE_MARGIN` (0.10) | `ROUTED_AMBIGUOUS` | `app/routing.py:150` |
| 3 | **Low confidence** | `score < CONFIDENCE_REVIEW_THRESHOLD` (0.50) | `ROUTED_LOW_CONFIDENCE` | `app/routing.py:166` |
| 4 | **Sensitivity** | any cited chunk is `internal` / `restricted` | `ROUTED_SENSITIVE` | `app/routing.py:179` |
| 5 | **Ungrounded** | the draft failed the grounding gate (lowest precedence) | `ROUTED_UNGROUNDED` | `app/routing.py:192` |

This covers both required cases — low confidence (#3) and policy-sensitive (#1 high-risk tags, #4
sensitivity) — plus three defense-in-depth triggers.

**Which team it routes to** (the receiving party) — queues are **never hardcoded**; they come from the
loaded policy map or the `DEFAULT_REVIEWER_QUEUE` (`engineering`):
- For a high-risk tag (#1), the matched tag is looked up directly in `routing_map`
  (`_resolve_queue_for_high_risk_tag`, `app/routing.py:74`).
- For #2/#3/#5, iterate the item's tags in order and take the first that maps
  (`_resolve_queue`, `app/routing.py:61`).
- For #4, route to `SENSITIVITY_REVIEW_QUEUE` (`compliance`).

The map lives in `data/policy_tags.synthetic.json` — e.g. `legal→legal`, `security→security`,
`encryption→security`, `infrastructure→engineering`, `certification→gtm`. Available queues:
`security, legal, engineering, gtm, compliance` (`REVIEWER_QUEUES`, `app/config.py:87`).

**The explicit exception path** (`app/pipeline.py:401`): when `should_route` is true, the agent
transitions `SCORED → ROUTED_FOR_REVIEW` (`actor="agent"`) and writes a `state_transition` audit event
carrying the firing `RULE_*`, the `queue`, and the `reason_code`. The item is now "stuck" at
`ROUTED_FOR_REVIEW` — the agent will **not** advance it further (only a human can).

**Auto-tagging untagged items** (`infer_tags`, `app/pipeline.py:88`): if an item arrives with no
`topic_tags`, the system infers them from its retrieved chunks (BM25-score-weighted, filtered to the
valid tag vocabulary, top `AUTO_TAG_MAX`=3) so routing still works. An item that already has tags is
respected unchanged.

### Concrete example — DEMO2 (`case_review`)
Both items are tagged `["legal", "compliance", "security"]`. Trigger #1 fires on `legal`, queue resolves
to `legal`, reason `ROUTED_HIGH_RISK`. Both items are routed, banner-flagged, and **never exported** —
the textbook "human-review exception." In DEMO1, i3 (MFA, tag `security`) is *high confidence* (0.880)
yet still routes via #1 — **defense-in-depth: a high-risk tag overrides high confidence**
(`scripts/run_demo.py:132`).

### Defensible talking point
> "Routing is a strict precedence ladder with five triggers, and the destination queue is data-driven,
> never hardcoded. A high-risk legal/security tag routes *even when the model is confident* — we'd
> rather over-route to a human than ship an unreviewed legal position."

---

## 6. Status Updates — How the system reports questionnaire status in real time

### What the assignment asks
The flow must include **real-time status updates**, and integrate with internal **SLA / workflow**
systems. Show defined **state changes** — e.g. "received" → "retrieving" → "awaiting legal review" →
"final draft ready for export."

### How it is implemented — an explicit, guarded state machine
Status is not an ad-hoc flag; it is a formal state machine. The states are declared once in
`ITEM_STATES` (`app/config.py:101`):

```
INTAKE → RETRIEVED → DRAFTED → SCORED →
   ├── ROUTED_FOR_REVIEW → REVIEW_APPROVED / REVIEW_REJECTED
   └── (confident) ───────────────────────────────────────→ APPROVED → EXPORTED
```

**Legal transitions are a graph, illegal ones raise** (`LEGAL_TRANSITIONS`, `app/state.py:71`). The
single enforcement point is `transition(current, target, *, actor)` (`app/state.py:107`):
- a non-edge raises `InvalidTransition` (`STATUS1`) — you cannot skip or jump states;
- a human-only target attempted by the agent raises `SelfApproveBlocked` (Q-relevant to §7 too).

**Real-time updates = each transition is audited as it happens.** As the pipeline runs each item it
emits a `state_transition` audit event at every hop (`INTAKE→RETRIEVED` at `app/pipeline.py:248`,
`RETRIEVED→DRAFTED` at `:329`, `DRAFTED→SCORED` at `:364`, `SCORED→ROUTED_FOR_REVIEW` at `:403`). The
JSONL audit log is therefore a **live, append-only status feed** — a monitor tailing the file sees the
questionnaire move through "retrieving → drafted → scored → awaiting review" in order.

**Mapping to the assignment's example statuses:**
- "received" = `INTAKE`
- "retrieving" = the `INTAKE → RETRIEVED` transition
- "awaiting legal review" = `ROUTED_FOR_REVIEW` with `queue="legal"`
- "final draft ready for export" = `APPROVED` (a human-gated state, ready for `export`)

**The human gate is part of the state model.** `REVIEW_APPROVED`, `REVIEW_REJECTED`, `APPROVED`,
`EXPORTED` are `HUMAN_ONLY_TARGETS` (`app/state.py:95`) — the agent can drive an item up to `SCORED` /
`ROUTED_FOR_REVIEW`, but only `actor="human"` advances it to approved/exported. This is exactly the
"awaiting legal review" → "ready for export" handoff, with the SLA/turnaround being an organizational
layer on top of these states. Two ways to exercise the gate:
- **Auto-simulated** (`make demo`, `scripts/run_demo.py`): confident, non-sensitive items are approved
  automatically (still `actor="human"`) so the demo runs end-to-end unattended.
- **Interactive reviewer** (`scripts/run_questionnaire.py --approve`): the operator reviews **each item**
  and types `[a]pprove / [r]eject / [s]kip`. A routed item walks the real human path
  `ROUTED_FOR_REVIEW → REVIEW_APPROVED → APPROVED`; a reject becomes `REVIEW_REJECTED` and stays
  unexported. Every human decision writes its own `state_transition` audit event
  (`rule=RULE_NO_SELF_APPROVE`, `actor="human"`).

### Defensible talking point
> "Status is a typed state machine, not a string someone sets by hand. Illegal jumps raise, and every
> legal transition is written to an append-only log the instant it happens — so the audit log doubles
> as the real-time status feed an SLA system would subscribe to."

---

## 7. Audit Log — How every action and decision is recorded

### What the assignment asks
The system must produce a complete **audit log**, and the pipeline must produce an **auditable response
document**. The code must show *active writing* into the audit log. The technical appendix + demo must
show the **logging design**: which rules fired, which guardrails/validations passed or failed, the
routing decisions, and who approved what.

### How it is implemented — append-only JSONL, one event per step
`RULE_AUDIT_COMPLETE`: **every state transition and every tool call emits exactly one append-only audit
event** — no silent gaps. The logger is `app/audit.py`.

**Event schema** — `AuditEvent` (`app/schema.py:129`), one JSON line per event:

```
timestamp, questionnaire_id, item_id, event,
from_state, to_state, rule, detail{...}
```

`event` is the kind (`tool_call`, `state_transition`, `export`, `error_terminal`, …); `rule` carries
the firing `RULE_*` identifier; `detail` is structured per-step data.

**Active writing** (`write_audit`, `app/audit.py:136`):
- the `audit/` directory is created **lazily** (never at import — import-safety, `ENV4`);
- the file is opened in **append mode** — the log is never truncated or rewritten (tamper-evident);
- one `json.dumps(...) + "\n"` per call — strictly one line per event.

**Security of the log itself** (`redact`, `app/audit.py:57`): before writing, every detail is
recursively scrubbed — Anthropic keys (`sk-ant-…`), `ANTHROPIC_API_KEY=…`, emails, and phone numbers
are replaced with `[REDACTED-*]` sentinels (`RULE_NO_SECRET` / `RULE_NO_REAL_PII`). The spine of trust
never itself holds a secret or real PII.

**What gets recorded across one item's life** (all in `app/pipeline.py`) — this is the "dramatic steps"
trail the assignment asks for:

| Step | Event written | Captures |
|---|---|---|
| intake | `tool_call` (intake) | the question received | 
| refine_query | `tool_call` (refine_query) | original vs optimized query |
| retrieve | `tool_call` (retrieve) | `n_chunks`, the `chunk_ids` returned |
| state change | `state_transition` | `INTAKE → RETRIEVED` |
| auto_tag | `tool_call` (auto_tag) | inferred tags (if any) |
| assemble_context | `tool_call` | number of retrieval entries |
| **draft + grounding** | `tool_call` (draft_answer) | `grounded` bool, **`reason_code` = `GROUNDING_FAIL`** if the guardrail failed, `n_citations` |
| score | `tool_call` (score_confidence) | the **score** + rationale |
| **route** | `tool_call` + `state_transition` | `should_route`, **queue**, **reason_code** (which trigger fired), the firing `RULE_*` |
| **human approval** | `state_transition` | `rule=RULE_NO_SELF_APPROVE`, `detail={"actor":"human","action":"APPROVED"}` — **who approved what** (`scripts/run_demo.py:156`) |
| export | `export` | `rule=RULE_NO_EXTERNAL_SEND`, `destination=local_disk`, paths, exported/held counts |
| failure | `error_terminal` | `rule=RULE_SAFE_TERMINAL`, `reason=ERROR_TERMINAL`, the error |

So the log literally answers: **which rules fired** (the `rule` field), **which guardrails
passed/failed** (`grounded`, `GROUNDING_FAIL`, `SENSITIVITY_HOLD`), **the routing decisions** (queue +
reason-code), and **who approved what** (the human `state_transition`).

**The auditable response document** is the *output* side of the same trust spine: `export_response`
(`app/export.py:212`) writes Markdown + CSV for **APPROVED items only**, holds `internal`/`restricted`
items behind the sensitivity gate (`SENSITIVITY_HOLD`), and emits an affirmative
`RULE_NO_EXTERNAL_SEND` audit event proving `destination=local_disk`. The send-ready document
(`render_response_document`, `app/export.py:175`) strips internal machinery and shows a human-readable
`Source:` line per answer.

### What to show in the demo
`make demo`, then open `audit/q-review-001.jsonl` — show the unbroken sequence of one-line events for a
single item, point at a `ROUTED_HIGH_RISK` line (a guardrail firing) and the export line
(`EXTERNAL_SEND_BLOCKED` / `destination=local_disk`). Then open the exported `.md` to show the
auditable response document.

### Defensible talking point
> "Every dramatic step — every tool call, every state change, every rule that fired, every human
> approval — is one append-only JSONL line, with secrets and PII redacted before writing. The audit log
> is the system of record: it's how Security/Legal can reconstruct exactly why any answer was shipped,
> and the exported document is the human-reviewed, approved-only artifact that flows from it."

---

## Appendix — The `RULE_*` guardrail registry (one-glance)

| `RULE_*` | What it guarantees | Chokepoint |
|---|---|---|
| `RULE_GROUNDED_ONLY` | no asserted answer without a cited retrieved chunk; else placeholder + route | `app/draft.py` `grounding_check` |
| `RULE_HITM_REVIEW_TRIGGER` | risky items route to a human (5 triggers, precedence) | `app/routing.py` |
| `RULE_NO_SELF_APPROVE` | only a human reaches APPROVED/EXPORTED | `app/state.py` `transition` |
| `RULE_NO_EXTERNAL_SEND` | export is local-disk-only, approved items only | `app/export.py` |
| `RULE_SENSITIVITY_GATE` | internal/restricted never exports without human review | `app/export.py` + `app/routing.py` |
| `RULE_AUDIT_COMPLETE` | one append-only event per transition + tool call | `app/audit.py` |
| `RULE_SAFE_TERMINAL` | any failure → clean routed terminal + audit; never a crash | `app/pipeline.py` |
| `RULE_NO_SECRET` / `RULE_NO_REAL_PII` | keys/PII never in a tracked file/log/export | `.gitignore` + `redact()` |
| `RULE_NO_EVAL_CONTAMINATION` / `RULE_NO_FABRICATED_METRIC` | held-out eval; every metric computed, never hardcoded | `app/eval/*` |

**Reproduce it all:** `make test` (offline deterministic suite), `make demo` (both demo cases),
`make eval` (Recall@K / grounding / routing / calibration), `make demo-live` (gated Claude lane).
All numbers trace to `FACTS.md`.
