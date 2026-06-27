# AI Operations Engineer | Reindeer Interview Exercise
**Internal AI agent demo + stakeholder-facing business walkthrough**

| FORMAT | TOOLS | GOAL |
| :--- | :--- | :--- |
| Claude Code demo + 20-min walkthrough | Claude Code. API key will be provided before the interview. | Build a lightweight internal AI agent workflow, then translate it into business and operating value. |

---

## THE SCENARIO

Reindeer's AEs and Solutions Engineers spend a meaningful share of every enterprise deal cycle filling out customer security questionnaires and RFP/RFI responses — including bespoke enterprise security and legal docs. 

Today the process is mostly manual: 
* People hunt for prior answers across Google Drive.
* Copy-paste from past deals.
* Route the unanswerable items to Security, Legal, or Engineering.
* Chase reviewers for sign-off.

**The question for you:** Can Reindeer deploy an internal AI agent that ingests a new questionnaire, drafts safe responses from a knowledge base of prior approved answers and product/security docs, flags low-confidence or policy-sensitive items for human review, routes those to the right reviewer, and produces an auditable, exportable response document?

---

## YOUR ASSIGNMENT

### 1. Build the Agent Flow
Build a Claude Code demo for security questionnaire / RFP response drafting. Show the agent moving from intake to a final exportable response.

* **Core Pipeline Requirements:** Include trigger/input (a new questionnaire), knowledge base retrieval, draft generation, confidence scoring, reviewer routing, status updates, and an audit log.
* **Fidelity:** Lightweight working demo, mocked demo, or well-structured pseudo-implementation in Claude Code.

### 2. Show Technical Depth
* **Implementation Details:** Include one prompt/tool-call pattern, a structured output/schema, a validation or guardrail, and an exception path.
* **System Interactions:** Show at least three mocked or simulated system interactions:
  1. Retrieving prior Q&A from a knowledge base.
  2. Checking policy or sensitivity tags.
  3. Drafting answers.
  4. Routing items to a reviewer.
  5. Writing the audit log.

### 3. Internal Stakeholder Walkthrough
* **Target Audience:** Present as if speaking to Reindeer's internal stakeholders — AEs, SEs, Security, Legal — not only to engineers.
* **Business Impact:** Explain the business impact: cycle time, win rate, accuracy, compliance posture, and GTM capacity.
* **Human-in-the-Loop:** Explain where humans stay in control and what must be true before this is rolled out internally.
* **Future Roadmap:** Recommend the next internal automation opportunity after the first successful rollout.

> **DEMO CASES REQUIRED:** Show two demo cases: a **confident auto-draft** and a **human-review exception**.

---

## WHAT TO DELIVER

* **Claude Code Demo:** Working, mocked, or well-structured pseudo-demo is fine.
* **Brief or Deck (1-2 pages/slides):** Workflow, architecture, assumptions, and success metrics.
* **Technical Appendix:** Prompt/tool design, data schema, guardrails, state changes, reviewer routing, and audit/logging.
* **Presentation:** 20-minute walkthrough, followed by 20 minutes of technical Q&A.

---

## KEEP IN MIND / DESIGN CONSTRAINTS

* **No UI Polish:** Do not over-invest in polished UI. We care about agent/workflow design and technical judgment.
* **Mock Data:** Use fake data only, and state your assumptions clearly.
* **Hard Boundary:** Do not auto-send anything externally — **human approval is required** before any response leaves the company.
* **Tradeoffs & Judgment:** Be ready to explain tradeoffs: build vs. buy, deterministic logic, LLM help, tools/APIs, and human control. 

*We should leave knowing you can build, debug, and explain real internal automation.*

---

## HOW WE EVALUATE

| AGENT DESIGN | TECHNICAL EXECUTION | INTEGRATION & WORKFLOW | BUSINESS JUDGMENT | COMMUNICATION |
| :--- | :--- | :--- | :--- | :--- |
| Clear decomposition into steps, tools, decisions, state changes, and handoffs. | Uses Claude Code, mocked tools/APIs, schemas, prompts, validation, guardrails, and logs thoughtfully. | Shows how the agent fits Reindeer's internal stack: knowledge base, reviewer routing, exception handling, SLAs, and system updates. | Balances automation with compliance risk, internal trust, build-vs-buy judgment, and human review. | Explains technical work in stakeholder language and ties it to measurable value. |

---

**Note:** We are not grading production polish. We are looking for whether you can translate a messy internal workflow into a credible, safe, and useful AI agent demo that Reindeer would actually deploy on itself.

**Good luck!**