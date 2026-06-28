# Empirical Sweep — PR-3 (ungrounded-token cap N) & PR-4 (boundary band)

**Date:** 2026-06-28 · **By:** PM (verifier) · **Status:** read-only sweep for Asaf to pin `N` and the band. No graded change made.
**Source:** `redteam/live_review_50.jsonl` (50 live drafts). Coverage + absolute ungrounded-token counts
**reconstructed deterministically** (real `retrieve` → `assemble_context` → `_cited_chunks_text` → `_significant_tokens`).
**Replication check:** my recomputed coverage matches the stored `grounding_diag.coverage` on **50/50** items (±0.01) → the reconstruction is faithful.

---

## PR-3 — absolute ungrounded significant-token cap `N`

Only **grounded + not-routed** items can "ship" un-reviewed, so the cap is calibrated against those 24 items.
`ungrounded_abs = |significant_tokens(draft) − significant_tokens(cited_chunks)|`.

| id | draft sig-tokens | coverage | **ungrounded_abs** | note |
|---|---:|---:|---:|---|
| **BO-013** | 125 | 0.592 | **51** | the genuine padder (PR-3's target) |
| BO-029 | 79 | 0.582 | 33 | contentless — already caught by **PR-2** |
| BO-036 | 135 | 0.763 | 32 | **legit long answer** (76% covered) — must NOT be flagged |
| BO-026 | 71 | 0.563 | 31 | the boundary flipper — PR-4's target |
| BO-008 | 51 | 0.608 | 20 | … tail ≤ 20 below here |

**Candidate `N` → how many grounded+not-routed items get newly flagged (`ungrounded_abs > N`):**

| N | flagged | which |
|---:|---:|---|
| 30 | 4 | BO-013, BO-029, BO-036, BO-026 ← **false-positives** (BO-036 is 76%-covered) |
| 40 | 1 | BO-013 |
| **45–50** | **1** | **BO-013 only** ✅ |
| 55+ | 0 | misses BO-013 |

**Recommendation: `N = 50`** (`GROUNDING_MAX_UNGROUNDED_TOKENS`). Any value in **[33, 50]** isolates BO-013 alone;
50 sits just under BO-013's 51 with comfortable clearance above the legitimate BO-036 (32) and the contentless
BO-029 (33, which PR-2 handles anyway). **Caveat:** this is calibrated on **one** positive (BO-013) over 50 live
samples — the 33→51 gap is wide so it isn't over-fit, but re-validate `N` once more live data exists.

---

## PR-4 — boundary buffer band (content-coverage)

The only **confirmed cross-run flipper that is currently grounded + not-routed** is **BO-026 (coverage 0.563)**.
The cliff zone:

| id | coverage | grounded | routed | already handled by |
|---|---:|:---:|:---:|---|
| BO-014 | 0.475 | ✗ | ✓ | < 0.50 → PR-1 / low-conf (below the cliff) |
| eval-003 | 0.562 | ✓ | ✓ | high-risk (safe) |
| **BO-026** | **0.563** | ✓ | **✗** | **nothing — PR-4's target** |
| eval-004 | 0.567 | ✓ | ✓ | sensitive (safe) |
| BO-029 | 0.582 | ✓ | ✗ | PR-2 (contentless) |
| BO-013 | 0.592 | ✓ | ✗ | PR-3 (padding) |
| q-confident-001-i2 | 0.600 | ✓ | ✓ | sensitive (safe) |

**⚠️ Correction to the audit's proposal.** DN-QA50/PR-4 suggested the band **`0.45 ≤ coverage < 0.55`** — but that
**misses BO-026 (0.563)**, the very item PR-4 exists to stabilize. The band must extend above 0.563.

**Recommendation: band `0.50 ≤ coverage < 0.60`** (route-for-review, don't auto-draft). This catches BO-026; the
items it also touches (eval-003/004, q-confident-i2) are **already routed** for other reasons (no new effect), and
BO-029/BO-013 are caught by PR-2/PR-3. **The elegant part:** PR-1 routes the *below-0.50* (ungrounded) side and PR-4
routes the *0.50–0.60 grounded* side, so a borderline item is **always routed regardless of which way the live
wobble lands** → the cross-run flip becomes invisible (consistently human-reviewed).

**Two things to resolve before PR-4 is pinned (why it stays DEFERRED):**
1. **Home / data-flow.** `route_for_review` does not currently receive `coverage`; PR-4 needs it threaded in
   (additive kwarg, like PR-1's `grounded`) or implemented in `confidence`. Decide the home.
2. **Offline byte-identical check.** Confirm NO offline (`MockLLM`) test/eval item has coverage in `[0.50, 0.60)`
   — MockLLM echoes chunks so coverage is typically ≫ 0.60, but this must be verified or PR-4 would change gold.

---

## Bottom line for the pin
- **PR-3:** `GROUNDING_MAX_UNGROUNDED_TOKENS = 50` (range [33,50] equivalent; flags only BO-013). Revisit with more data.
- **PR-4:** band `[0.50, 0.60)` (NOT the audit's [0.45,0.55), which misses BO-026); resolve home + offline-impact before pinning.
