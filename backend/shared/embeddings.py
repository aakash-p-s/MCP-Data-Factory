"""Embedding config — the SINGLE source of truth (Codebase PRD §5.1.2).

The loader (infra/synthea/load_patients.py) and the vector connector
(backend/connectors/vector_connector.py, Jul 6) MUST embed with the identical model.
A mismatch doesn't error on its own — it silently returns meaningless similarity
results. So both sides import from HERE; neither reads the model name itself.

Two protections:
  1. One place defines the model + collection + dimension. Nobody can drift.
  2. ensure_collection() stamps the model name into the collection; the connector
     calls assert_model_matches() on startup and crashes LOUDLY on any mismatch.

Heavy deps (sentence-transformers, qdrant-client) are imported lazily so merely
importing this module stays cheap.
"""

from __future__ import annotations

import os
from functools import lru_cache

# --- the single source of truth ---------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
COLLECTION = "clinical_notes"
_META_ID = 0  # reserved point id holding the embedding fingerprint (not a real note)


@lru_cache(maxsize=1)
def get_model():
    """Load the SentenceTransformer once and reuse it (lru_cache singleton)."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


def embed(text: str) -> list[float]:
    """Embed one string. normalize_embeddings keeps cosine distance consistent."""
    return get_model().encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in get_model().encode(texts, normalize_embeddings=True)]


def embedding_dim() -> int:
    """Derived from the model — never hardcode 384 anywhere else."""
    m = get_model()
    # method was renamed get_sentence_embedding_dimension -> get_embedding_dimension
    fn = getattr(m, "get_embedding_dimension", None) or m.get_sentence_embedding_dimension
    return fn()


# --- collection lifecycle + fingerprint guard --------------------------------
def ensure_collection(client) -> None:
    """(Re)create the collection with the right dim/distance and stamp the model.

    Called by the loader. The stamp lets the connector detect a model mismatch.
    """
    from qdrant_client.models import Distance, PointStruct, VectorParams

    dim = embedding_dim()
    client.recreate_collection(
        COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
    client.upsert(COLLECTION, points=[PointStruct(
        id=_META_ID,
        vector=[1.0] + [0.0] * (dim - 1),   # non-zero sentinel; excluded from searches
        payload={"_meta": True, "embedding_model": EMBEDDING_MODEL, "dim": dim})])


def assert_model_matches(client) -> None:
    """Raise loudly if the collection was built with a different model. Call on connect."""
    recs = client.retrieve(COLLECTION, ids=[_META_ID])
    if not recs:
        raise RuntimeError(
            f"Collection '{COLLECTION}' has no embedding fingerprint — reseed with the loader.")
    built_with = recs[0].payload.get("embedding_model")
    if built_with != EMBEDDING_MODEL:
        raise RuntimeError(
            f"Embedding model mismatch: collection '{COLLECTION}' was built with "
            f"'{built_with}', but this process queries with '{EMBEDDING_MODEL}'. "
            f"Reseed the loader or fix EMBEDDING_MODEL — results would be meaningless.")


def exclude_meta_filter():
    """Filter for searches so the reserved fingerprint point is never returned."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    return Filter(must_not=[FieldCondition(key="_meta", match=MatchValue(value=True))])
