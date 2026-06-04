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


def build_qdrant_conditions(
    request: SearchRequest,
    entity_type: str,
) -> List[FieldCondition]:
    conditions: List[FieldCondition] = [
        FieldCondition(key="businessStatus", match=MatchValue(value="APPROVED")),
        FieldCondition(key="isAvailable", match=MatchValue(value=True)),
    ]
    if entity_type == "service":
        conditions.append(FieldCondition(key="isEnabled", match=MatchValue(value=True)))
        conditions.append(FieldCondition(key="isDisplay", match=MatchValue(value=True)))

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
    entity_type: str,
    hydrated: dict,
    businesses: dict = None,
) -> Optional[SearchResult]:
    doc = hydrated.get(ranked["id"])
    if not doc:
        return None

    if entity_type == "business":
        highlight = ResultHighlight(
            name=doc.get("businessName", ""),
            description=str(doc.get("description", ""))[:120] or None,
        )
        business_summary = BusinessSummary(
            id=ranked["id"],
            name=doc.get("businessName", ""),
            rating=float(doc.get("overallRating") or 0.0),
            xirifyAssured=bool(doc.get("xirifyAssured", False)),
        )
        return SearchResult(
            entityType="business",
            id=ranked["id"],
            score=round(ranked["final_score"], 4),
            distanceKm=ranked["distance_km"],
            business=business_summary,
            highlight=highlight,
        )

    if entity_type == "service":
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
    return None


async def search(request: SearchRequest) -> SearchResponse:
    from app.core.embedder import embed_query
    from app.core.reranker import compute_final_scores, rrf_fuse
    from app.db import mongo as mongo_db
    from app.db import qdrant as qdrant_db

    t0 = time.monotonic()
    normalized = normalize_query(request.query)
    query_vector = await embed_query(normalized)

    all_results = []
    fallback_used = False

    entity_types = request.entities or ["business", "service"]

    async def search_entity(entity_type: str):
        conditions = build_qdrant_conditions(request, entity_type)

        vector_hits = await qdrant_db.search_vectors(
            entity_type, query_vector, conditions, limit=40
        )

        if entity_type == "business":
            text_hits = await mongo_db.text_search_businesses(normalized, limit=40)
        else:
            text_hits = await mongo_db.text_search_services(normalized, limit=40)

        fused = rrf_fuse(vector_hits, text_hits)

        if not fused:
            return [], False

        consumer_lat = request.geo.lat if request.geo else 0.0
        consumer_lng = request.geo.lng if request.geo else 0.0
        ranked = compute_final_scores(fused, consumer_lat, consumer_lng)

        above_threshold = [r for r in ranked if r["final_score"] >= _SCORE_THRESHOLD]
        used_fallback = len(above_threshold) == 0

        if used_fallback:
            above_threshold = ranked[:20]

        ids = [r["id"] for r in above_threshold]
        mongo_collection = "businesses" if entity_type == "business" else "services"
        hydrated = await mongo_db.hydrate_by_ids(mongo_collection, ids)

        businesses = {}
        if entity_type == "service":
            biz_ids = list({
                str(doc.get("businessId", ""))
                for doc in hydrated.values()
                if doc.get("businessId")
            })
            businesses = await mongo_db.hydrate_by_ids("businesses", biz_ids)

        results = []
        for ranked_item in above_threshold:
            result = _to_search_result(ranked_item, entity_type, hydrated, businesses)
            if result:
                results.append(result)

        return results, used_fallback

    tasks = [search_entity(et) for et in entity_types]
    entity_results_list = await asyncio.gather(*tasks)

    for entity_results, entity_fallback in entity_results_list:
        all_results.extend(entity_results)
        if entity_fallback:
            fallback_used = True

    all_results.sort(key=lambda r: r.score, reverse=True)
    offset = (request.page - 1) * request.limit
    page_results = all_results[offset : offset + request.limit]

    return SearchResponse(
        results=page_results,
        fallbackUsed=fallback_used,
        total=len(all_results),
        tookMs=int((time.monotonic() - t0) * 1000),
    )
