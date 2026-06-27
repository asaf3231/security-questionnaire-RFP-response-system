"""
app/retrieval.py — Deterministic lexical retrieval via rank_bm25.

Responsibility: given a question (and optional tag filters), retrieve the top-K
approved KB chunks scored by BM25Okapi, returning them as RetrievedChunk objects
with bm25_score set.

Design notes:
- The Retriever class builds the BM25Okapi index over the FULL approved corpus ONCE
  at construction time (standard RAG pattern — stable corpus-level IDF). The pipeline
  instantiates one Retriever and reuses it across all items (D-S6, Asaf req #2).
- The module-level retrieve() function is the graded contract; it now delegates to a
  per-call Retriever(load_kb()) for backward-compatibility. Production callers should
  build a Retriever once and call retriever.retrieve() directly.
- Corpus indexing = approved==True only (KB1: non-approved chunks are never retrievable
  regardless of other filters).
- Ranking uses rank_bm25 BM25Okapi with params BM25_K1 and BM25_B from config.py.
  Do NOT hand-roll BM25 (Asaf principle B, D-2).
- Tokenization is deterministic: lowercase + re.split on non-alphanumeric characters.
  The document text per chunk is: chunk.question + " " + chunk.answer (if question
  exists) or just chunk.answer. Same tokenizer applied to the query.
- Full-corpus index then filter: the BM25 index is built over the FULL approved corpus;
  filters (topic/sensitivity) are applied AFTER scoring, before top-k selection.
  This is the standard RAG pattern (stable corpus-level IDF). Note: this changes BM25
  raw scores vs a per-filtered-corpus index but the rank ordering stays consistent for
  high-coverage queries (see RET1/RET2/RET3 which remain green).
- Tiebreak: results are sorted descending by bm25_score with a deterministic secondary
  sort by chunk_id (ascending) so that RET3 holds across runs.
- Import-safe: no side effects at import — all work happens inside function/method calls.
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
# Retriever class — builds the BM25 index ONCE over the full approved corpus
# ---------------------------------------------------------------------------

class Retriever:
    """Deterministic BM25 retriever that builds the index once at construction.

    The BM25Okapi index is built over ALL approved chunks at __init__ time so
    that IDF weights are stable across queries (standard RAG pattern, D-S6).
    Topic/sensitivity filters are applied AFTER scoring, before top-k selection.

    Usage (pipeline):
        retriever = Retriever(load_kb())  # build once
        for item in questionnaire["items"]:
            chunks = retriever.retrieve(item.question, topic_tags=item.topic_tags)
    """

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        """Build the BM25Okapi index over approved chunks.

        Parameters
        ----------
        chunks:
            All KB chunks (approved + non-approved); only approved==True chunks
            are indexed (KB1).
        """
        # Filter to approved only — KB1 invariant
        self._approved: list[RetrievedChunk] = [c for c in chunks if c.approved]

        if self._approved:
            tokenized_corpus = [_tokenize(_chunk_text(c)) for c in self._approved]
            self._bm25 = BM25Okapi(tokenized_corpus, k1=BM25_K1, b=BM25_B)
        else:
            self._bm25 = None

    def retrieve(
        self,
        question: str,
        *,
        topic_tags: Optional[list[str]] = None,
        allowed_sensitivities: Optional[list[str]] = None,
        top_k: int = RETRIEVAL_TOP_K,
    ) -> list[RetrievedChunk]:
        """Return the top-K approved KB chunks most relevant to question.

        Scores the query against the full approved-corpus index, then applies
        topic/sensitivity filters to the scored results, then returns top-k.

        Parameters
        ----------
        question:
            The question text to retrieve evidence for.
        topic_tags:
            If non-empty, restrict results to chunks sharing ≥1 topic tag.
        allowed_sensitivities:
            If provided, restrict results to chunks whose sensitivity ∈ this list.
            Default None = all sensitivities pass.
        top_k:
            Maximum number of chunks to return (≤ RETRIEVAL_TOP_K).

        Returns
        -------
        list[RetrievedChunk]
            Up to top_k chunks, sorted descending by bm25_score with chunk_id as
            the deterministic tiebreak (ascending). bm25_score is set on each chunk.
            Returns an empty list if the corpus is empty or all filtered out.
        """
        if not self._approved or self._bm25 is None:
            return []

        # Score query against the full approved-corpus index
        tokenized_query = _tokenize(question)
        scores = self._bm25.get_scores(tokenized_query)

        # Attach scores to chunks
        scored: list[tuple[float, str, RetrievedChunk]] = []
        for chunk, score in zip(self._approved, scores):
            scored_chunk = chunk.model_copy(update={"bm25_score": float(score)})
            scored.append((float(score), chunk.chunk_id, scored_chunk))

        # Apply tag/sensitivity filters AFTER scoring
        if topic_tags:
            topic_set = set(topic_tags)
            scored = [t for t in scored if topic_set.intersection(t[2].topic_tags)]

        if allowed_sensitivities is not None:
            sens_set = set(allowed_sensitivities)
            scored = [t for t in scored if t[2].sensitivity in sens_set]

        # Sort: descending score, then ascending chunk_id (deterministic tiebreak)
        scored.sort(key=lambda t: (-t[0], t[1]))

        return [t[2] for t in scored[:top_k]]


# ---------------------------------------------------------------------------
# retrieve() — the graded contract (do NOT change the signature; surface as
# DECISION-NEEDED if the signature must change).
# Delegates to Retriever(load_kb()) so there is ONE retrieval code path.
# ---------------------------------------------------------------------------

def retrieve(
    question: str,
    *,
    topic_tags: Optional[list[str]] = None,
    allowed_sensitivities: Optional[list[str]] = None,
    top_k: int = RETRIEVAL_TOP_K,
) -> list[RetrievedChunk]:
    """Return the top-K approved KB chunks most relevant to question.

    Delegates to Retriever(load_kb()) — the single retrieval code path.
    The pipeline should build one Retriever and call retriever.retrieve() directly
    for efficiency; this function is the backward-compatible module-level entry point.

    Parameters
    ----------
    question:
        The question text to retrieve evidence for.
    topic_tags:
        If non-empty, restrict results to chunks sharing ≥1 topic tag.
    allowed_sensitivities:
        If provided, restrict results to chunks whose sensitivity ∈ this list.
        Default None = all sensitivities pass.
    top_k:
        Maximum number of chunks to return (≤ RETRIEVAL_TOP_K).

    Returns
    -------
    list[RetrievedChunk]
        Up to top_k chunks, sorted descending by bm25_score with chunk_id as
        the deterministic tiebreak (ascending). bm25_score is set on each chunk.
        Returns an empty list if the corpus is empty after filtering.
    """
    retriever = Retriever(load_kb())
    return retriever.retrieve(
        question,
        topic_tags=topic_tags,
        allowed_sensitivities=allowed_sensitivities,
        top_k=top_k,
    )
