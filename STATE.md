# STATE.md — current checkpoint (OVERWRITE every session-end; never append)
Updated: 2026-06-27 13:55 · Workstream: BACKEND · HEAD: (stage-2-retrieval; verify w/ git)
Current stage: 2 — KB chunks + deterministic retrieval (`rank_bm25`) · Status: ✅ Complete (PM-verified)
Resume at: **Stage 3 — Context Stack (4-layer backpack) + draft generation + grounding** (`CTX1`–`CTX4`, `SCHEMA1`, `DRAFT1`–`DRAFT2`, `GROUND1`). HALTED here per Asaf's "halt at the Stage 2 boundary for manual review." When resuming: implement `app/context_stack.py` + `app/llm.py` (MockLLM + lazy gated ClaudeLLM) + `app/draft.py` (grounding_check → `UNGROUNDED_PLACEHOLDER` byte-exact, `RULE_GROUNDED_ONLY`). Graded contracts → reviewer gate fires.
Live-truth (re-verify, don't trust → FACTS.md is source of truth): offline suite 71 pass (39 S1 + 32 S2) via `make test` (venv active); Recall@5 = 1.0000 (12 fixtures, ≥ target 0.90, computed); retrieval deterministic; KB 20/19/5, 20 unique ids; `DRAFT_MODEL=claude-sonnet-4-6`. Tags: stage-0-spine → stage-1-env → stage-2-retrieval on `main`.
Open halts / decisions pending Asaf: HALTED at Stage 2 boundary for manual review (per instruction). No open decisions. (FYI carried: Stage 1 SEC1 strengthening accepted — NOTES D-S1.)
Last 3 superseded decisions (tombstones): none.
Disk-vs-ledger watch: Stage 6 efficiency follow-up logged (retrieve() rebuilds BM25 per call — build once in the pipeline). `make test` needs the `.venv` active (system py 3.10 lacks rank_bm25).
