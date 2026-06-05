from __future__ import annotations
import asyncio
import re
import time
from typing import List, Optional

from qdrant_client.models import FieldCondition, MatchValue

from app.models.search import (
    BusinessSummary,
    ResultHighlight,
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

_SCORE_THRESHOLD = 0.05


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


def build_qdrant_conditions(request: SearchRequest) -> List[FieldCondition]:
    conditions: List[FieldCondition] = [
        FieldCondition(key="businessStatus", match=MatchValue(value="APPROVED")),
        FieldCondition(key="isAvailable", match=MatchValue(value=True)),
        FieldCondition(key="isEnabled", match=MatchValue(value=True)),
        FieldCondition(key="isDisplay", match=MatchValue(value=True)),
    ]

    if request.geo:
        from app.db import qdrant as qdrant_db
        conditions.append(
            qdrant_db.build_geo_condition(
                request.geo.lat, request.geo.lng, request.geo.radiusKm
            )
        )

    if request.filters:
        if request.filters.category:
            conditions.append(
                FieldCondition(
                    key="category", match=MatchValue(value=request.filters.category)
                )
            )

    return conditions


def _to_search_result(
    ranked: dict,
    hydrated: dict,
    businesses: dict = None,
) -> Optional[SearchResult]:
    doc = hydrated.get(ranked["id"])
    if not doc:
        return None

    highlight = ResultHighlight(
        name=doc.get("service", ""),
        price=doc.get("cost", {}).get("fixedCost"),
        description=str(doc.get("description", ""))[:120] or None,
    )
    business_summary = None
    if businesses:
        biz_id = str(doc.get("businessId", ""))
        biz_doc = businesses.get(biz_id)
        if biz_doc:
            business_summary = BusinessSummary(
                id=str(biz_doc["_id"]),
                name=biz_doc.get("businessName", ""),
                rating=float(biz_doc.get("overallRating") or 0.0),
                xirifyAssured=bool(biz_doc.get("xirifyAssured", False)),
            )
    return SearchResult(
        entityType="service",
        id=ranked["id"],
        score=round(ranked["final_score"], 4),
        distanceKm=ranked["distance_km"],
        business=business_summary,
        highlight=highlight,
    )


async def search(request: SearchRequest) -> SearchResponse:
    from app.core.embedder import embed_query
    from app.core.reranker import compute_final_scores, rrf_fuse
    from app.db import node_api as mongo_db
    from app.db import qdrant as qdrant_db

    t0 = time.monotonic()
    normalized = normalize_query(request.query)
    query_vector = await embed_query(normalized)

    conditions = build_qdrant_conditions(request)

    vector_hits = await qdrant_db.search_vectors(
        "service", query_vector, conditions, limit=40
    )
    text_hits = await mongo_db.text_search_services(normalized, limit=40)

    fused = rrf_fuse(vector_hits, text_hits)

    all_results = []
    fallback_used = False

    if fused:
        consumer_lat = request.geo.lat if request.geo else 0.0
        consumer_lng = request.geo.lng if request.geo else 0.0
        ranked = compute_final_scores(fused, consumer_lat, consumer_lng)

        above_threshold = [r for r in ranked if r["final_score"] >= _SCORE_THRESHOLD]
        fallback_used = len(above_threshold) == 0
        if fallback_used:
            above_threshold = ranked[:20]

        ids = [r["id"] for r in above_threshold]
        hydrated = await mongo_db.hydrate_by_ids("services", ids)

        biz_ids = list({
            str(doc.get("businessId", ""))
            for doc in hydrated.values()
            if doc.get("businessId")
        })
        businesses = await mongo_db.hydrate_by_ids("businesses", biz_ids)

        for ranked_item in above_threshold:
            result = _to_search_result(ranked_item, hydrated, businesses)
            if result:
                all_results.append(result)

    all_results.sort(key=lambda r: r.score, reverse=True)
    offset = (request.page - 1) * request.limit
    page_results = all_results[offset : offset + request.limit]

    return SearchResponse(
        results=page_results,
        fallbackUsed=fallback_used,
        total=len(all_results),
        tookMs=int((time.monotonic() - t0) * 1000),
    )
