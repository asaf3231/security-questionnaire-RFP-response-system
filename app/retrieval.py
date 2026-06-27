"""
app/retrieval.py — Deterministic lexical retrieval via rank_bm25.

Responsibility: given a question (and optional tag filters), retrieve the top-K
approved KB chunks scored by BM25Okapi, returning them as RetrievedChunk objects
with bm25_score set.

Design notes:
- Corpus = load_kb() filtered to approved==True only (KB1: non-approved chunks are
  never retrievable regardless of other filters).
- Ranking uses rank_bm25 BM25Okapi with params BM25_K1 and BM25_B from config.py.
  Do NOT hand-roll BM25 (Asaf principle B, D-2).
- Tokenization is deterministic: lowercase + re.split on non-alphanumeric characters.
  The document text per chunk is: chunk.question + " " + chunk.answer (if question
  exists) or just chunk.answer. Same tokenizer applied to the query.
- Topic filter (strict): if topic_tags is non-empty, restrict the corpus to chunks
  sharing ≥1 topic tag before ranking.
- Sensitivity filter: if allowed_sensitivities is provided, restrict to chunks whose
  sensitivity ∈ allowed_sensitivities. Default None = all sensitivities pass.
  NOTE: the sensitivity GATE (blocking internal/restricted from export) is enforced
  downstream at routing/export (RULE_SENSITIVITY_GATE, Stages 4/5), NOT here.
  Retrieval intentionally sees all approved chunks so the agent can draft grounded
  answers; the gate protects the output, not the retrieval corpus.
- Tiebreak: results are sorted descending by bm25_score with a deterministic secondary
  sort by chunk_id (ascending) so that RET3 holds across runs.
- Import-safe: no side effects at import — all work happens inside the retrieve() call.
- No network, no .env, no data/* read at import.
"""

from __future__ import annotations

import re
from typing import Optional

from rank_bm25 import BM25Okapi

from app.config import BM25_B, BM25_K1, RETRIEVAL_TOP_K
from app.kb import load_kb
from app.schema import RetrievedChunk


# ---------------------------------------------------------------------------
# Tokenizer (deterministic — no locale or random state)
# ---------------------------------------------------------------------------

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alphanumeric runs. Returns a list of tokens.

    Always produces the same output for the same input (no stemming, no stopword
    lists that could vary by environment). Empty strings are filtered out.
    """
    return [tok for tok in _TOKEN_SPLIT_RE.split(text.lower()) if tok]


def _chunk_text(chunk: RetrievedChunk) -> str:
    """Produce the stable document text for BM25 indexing.

    If the chunk has a question, concatenate question and answer so BM25 sees
    the full semantic content. Otherwise use the answer alone.
    """
    if chunk.question:
        return chunk.question + " " + chunk.answer
    return chunk.answer


# ---------------------------------------------------------------------------
# retrieve() — the graded contract (do NOT change the signature; surface as
# DECISION-NEEDED if the signature must change).
# ---------------------------------------------------------------------------

def retrieve(
    question: str,
    *,
    topic_tags: Optional[list[str]] = None,
    allowed_sensitivities: Optional[list[str]] = None,
    top_k: int = RETRIEVAL_TOP_K,
) -> list[RetrievedChunk]:
    """Return the top-K approved KB chunks most relevant to question.

    Parameters
    ----------
    question:
        The question text to retrieve evidence for.
    topic_tags:
        If non-empty, restrict corpus to chunks sharing ≥1 topic tag (strict filter
        applied before ranking).
    allowed_sensitivities:
        If provided, restrict corpus to chunks whose sensitivity ∈ this list.
        Default None = all sensitivities pass (see module docstring for the
        deliberate design decision on sensitivity filtering at retrieval time).
    top_k:
        Maximum number of chunks to return (≤ RETRIEVAL_TOP_K).

    Returns
    -------
    list[RetrievedChunk]
        Up to top_k chunks, sorted descending by bm25_score with chunk_id as
        the deterministic tiebreak (ascending). bm25_score is set on each chunk.
        Returns an empty list if the corpus is empty after filtering.
    """
    # --- Build corpus: approved only, then apply tag/sensitivity filters ---
    all_chunks = load_kb()
    corpus = [c for c in all_chunks if c.approved]

    if topic_tags:
        topic_set = set(topic_tags)
        corpus = [c for c in corpus if topic_set.intersection(c.topic_tags)]

    if allowed_sensitivities is not None:
        sens_set = set(allowed_sensitivities)
        corpus = [c for c in corpus if c.sensitivity in sens_set]

    if not corpus:
        return []

    # --- Tokenize corpus and query ---
    tokenized_corpus = [_tokenize(_chunk_text(c)) for c in corpus]
    tokenized_query = _tokenize(question)

    # --- Score with BM25Okapi (pinned rank_bm25 library; params from config) ---
    bm25 = BM25Okapi(tokenized_corpus, k1=BM25_K1, b=BM25_B)
    scores = bm25.get_scores(tokenized_query)

    # --- Attach scores to chunks and sort: descending score, then ascending chunk_id ---
    scored: list[tuple[float, str, RetrievedChunk]] = []
    for chunk, score in zip(corpus, scores):
        # Create a copy of the chunk with bm25_score set
        scored_chunk = chunk.model_copy(update={"bm25_score": float(score)})
        scored.append((float(score), chunk.chunk_id, scored_chunk))

    # Primary sort: score descending; secondary sort: chunk_id ascending (deterministic tiebreak)
    scored.sort(key=lambda t: (-t[0], t[1]))

    # Return top_k results (only the RetrievedChunk objects)
    return [t[2] for t in scored[:top_k]]
