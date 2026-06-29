"""VectorConnector — Codebase PRD §5.3.

Concrete Connector for Qdrant, used by clinical_notes_search. Implements the SAME
Connector interface as SQLConnector — the pluggable-connector proof.

The URL is fixed at construction (egress-guard intent). query() supports read-only
vector search and payload-filtered scroll modes; writes are not exposed.
"""

from __future__ import annotations

import asyncio

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from backend.shared.connector_base import Connector
from backend.shared.embeddings import COLLECTION, assert_model_matches, embed, exclude_meta_filter
from backend.shared.self_healing import run_with_self_healing


def _patient_filter(patient_id: str, note_type: str | None = None) -> Filter:
    must = [FieldCondition(key="patient_id", match=MatchValue(value=patient_id))]
    if note_type:
        must.append(FieldCondition(key="note_type", match=MatchValue(value=note_type)))
    base = exclude_meta_filter()
    return Filter(must=must, must_not=base.must_not)


def _row(point) -> dict:
    payload = dict(point.payload or {})
    payload["id"] = point.id
    if hasattr(point, "score") and point.score is not None:
        payload["score"] = point.score
    return payload


class VectorConnector(Connector):
    def __init__(self, url: str):
        self._url = url
        self._client: AsyncQdrantClient | None = None
        self._verified = False

    async def connect(self) -> None:
        await run_with_self_healing(self._connect_once, reset=self._reset_client)

    async def _connect_once(self) -> None:
        if self._client is None:
            self._client = AsyncQdrantClient(url=self._url)
        if not self._verified:
            await asyncio.to_thread(self._verify_fingerprint)
            self._verified = True

    async def _reset_client(self) -> None:
        await self.close()
        self._verified = False

    def _verify_fingerprint(self) -> None:
        assert_model_matches(QdrantClient(url=self._url))

    async def auth(self) -> None:
        return None

    async def schema(self) -> dict:
        return await run_with_self_healing(self._schema_once, reset=self._reset_client)

    async def _schema_once(self) -> dict:
        await self.connect()
        info = await self._client.get_collection(COLLECTION)
        vectors = info.config.params.vectors
        size = vectors.size if hasattr(vectors, "size") else vectors["size"]
        return {
            "collection": COLLECTION,
            "vector_size": size,
            "payload_fields": [
                "patient_id", "note_date", "author", "note_type", "author_role", "text",
            ],
        }

    async def query(self, params: dict) -> list[dict]:
        """Read-only vector / filter query.

        modes:
          search   — {"mode":"search", "patient_id", "query_text", "limit"?}
          recent   — {"mode":"recent", "patient_id", "limit"?}
          by_type  — {"mode":"by_type", "patient_id", "note_type", "limit"?}
        """
        mode = params.get("mode")
        if mode not in ("search", "recent", "by_type"):
            raise ValueError(f"unsupported vector query mode: {mode!r}")
        if mode == "by_type" and not params.get("note_type"):
            raise ValueError("note_type is required for by_type queries")
        return await run_with_self_healing(
            lambda: self._query_once(params), reset=self._reset_client)

    async def _query_once(self, params: dict) -> list[dict]:
        mode = params["mode"]
        patient_id = params["patient_id"]
        limit = int(params.get("limit", 5))
        await self.connect()

        if mode == "search":
            query_text = params.get("query_text", "").strip()
            if not query_text:
                return []
            vector = await asyncio.to_thread(embed, query_text)
            flt = _patient_filter(patient_id)
            # qdrant-client >=1.10 replaced .search() with .query_points(); fall back to
            # .search() on older clients so this works across pinned versions.
            if hasattr(self._client, "query_points"):
                resp = await self._client.query_points(
                    collection_name=COLLECTION,
                    query=vector,
                    query_filter=flt,
                    limit=limit,
                    with_payload=True,
                )
                hits = resp.points
            else:
                hits = await self._client.search(
                    collection_name=COLLECTION,
                    query_vector=vector,
                    query_filter=flt,
                    limit=limit,
                    with_payload=True,
                )
            return [_row(h) for h in hits]

        flt = _patient_filter(
            patient_id,
            note_type=params.get("note_type") if mode == "by_type" else None,
        )
        points, _ = await self._client.scroll(
            collection_name=COLLECTION,
            scroll_filter=flt,
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )
        rows = [_row(p) for p in points]
        rows.sort(key=lambda r: r.get("note_date") or "", reverse=True)
        return rows[:limit]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
