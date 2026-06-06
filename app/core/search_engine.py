from __future__ import annotations
import re

from app.models.search import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)

_HINGLISH_SYNONYMS = {
    "chemist": "pharmacy medicine",
    "thali": "meal platter set",
    "sabzi": "vegetables",
    "mithai": "sweets dessert",
    "dhaba": "restaurant food",
}


def normalize_query(query: str) -> str:
    q = query.lower().strip()
    q = re.sub(r"\s+", " ", q)
    expansions = []
    for token, expansion in _HINGLISH_SYNONYMS.items():
        if token in q.split():
            expansions.append(expansion)
    if expansions:
        q = q + " " + " ".join(expansions)
    return q.strip()


def _to_search_result(ranked: dict) -> SearchResult:
    payload = ranked.get("payload") or {}
    return SearchResult(
        entityType="service",
        id=ranked["id"],
        serviceId=str(payload.get("serviceId") or ""),
    )


async def search(request: SearchRequest) -> SearchResponse:
    from app.core.embedder import embed_query
    from app.core.reranker import compute_final_scores, rrf_fuse
    from app.db import node_api as mongo_db
    from app.db import qdrant as qdrant_db

    normalized = normalize_query(request.query)
    query_vector = await embed_query(normalized)

    vector_hits = await qdrant_db.search_vectors(
        "service", query_vector, [], limit=40
    )
    text_hits = await mongo_db.text_search_services(normalized, limit=40)

    fused = rrf_fuse(vector_hits, text_hits)

    all_results = []

    if fused:
        ranked = compute_final_scores(fused, 0.0, 0.0)

        for ranked_item in ranked:
            all_results.append(_to_search_result(ranked_item))

    offset = (request.page - 1) * request.limit
    page_results = all_results[offset : offset + request.limit]

    return SearchResponse(results=page_results)
