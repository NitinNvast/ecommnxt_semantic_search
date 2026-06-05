from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.embedder import (
    SEMANTIC_FIELDS,
    build_source_text,
    embed_texts,
    is_semantic_field_changed,
    source_hash,
)
from app.db import node_api as mongo_db
from app.db import qdrant as qdrant_db
from qdrant_client.models import FieldCondition, MatchValue

logger = logging.getLogger(__name__)

ENTITY_COLLECTION_MAP = {
    "business": "businesses",
    "service": "services",
}

EMBEDDING_VERSION = "v1-te3s"


def _should_skip_service(entity: dict) -> bool:
    if entity.get("isAddOn"):
        return True
    variation_id = (entity.get("variation") or {}).get("variationGroupId")
    if variation_id and not entity.get("isDefaultVariationView"):
        return True
    return False


async def _resolve_taxonomy(entity_type: str, entity: dict) -> dict:
    if entity_type != "business":
        return {}
    resolved = {}
    cat_id = str(entity.get("category") or "")
    if cat_id:
        names = await mongo_db.get_taxonomy_names("categories", [cat_id])
        resolved["category_name"] = names.get(cat_id, "")

    brand_ids = [str(b) for b in (entity.get("brandIds") or [])]
    if brand_ids:
        names = await mongo_db.get_taxonomy_names("brands", brand_ids)
        resolved["brand_names"] = list(names.values())

    return resolved


def _build_business_payload(entity: dict) -> dict:
    loc = (entity.get("address") or {}).get("location") or {}
    coords = loc.get("coordinates") or []
    geo = None
    if len(coords) == 2:
        geo = {"lon": float(coords[0]), "lat": float(coords[1])}
    return {
        "entity_type": "business",
        "mongoId": str(entity.get("_id", "")),
        "businessId": str(entity.get("businessId", "")),
        "location": geo,
        "category": str(entity.get("category") or ""),
        "categoryType": str(entity.get("categoryType") or ""),
        "businessStatus": entity.get("businessStatus", "APPROVED"),
        "isAvailable": (entity.get("availability") or {}).get("status") == "ACTIVE",
        "overallRating": float(entity.get("overallRating") or 0),
        "uniqueReviewsCount": int(entity.get("uniqueReviewsCount") or 0),
        "xirifyAssured": bool(entity.get("xirifyAssured")),
        "topRated": bool(entity.get("topRated")),
        "popular": bool(entity.get("popular")),
        "isnew": bool(entity.get("isnew")),
        "sortOrder": int(entity.get("sortOrder") or 40),
        "serviceableArea": float(entity.get("serviceableArea") or 5),
        "serviceModes": entity.get("serviceModes") or [],
    }


def _build_service_payload(entity: dict, business: Optional[dict] = None) -> dict:
    geo = None
    if business:
        loc = (business.get("address") or {}).get("location") or {}
        coords = loc.get("coordinates") or []
        if len(coords) == 2:
            geo = {"lon": float(coords[0]), "lat": float(coords[1])}
    return {
        "entity_type": "service",
        "mongoId": str(entity.get("_id", "")),
        "businessId": str(entity.get("businessId", "")),
        "location": geo,
        "subcategory": str(entity.get("subcategory") or ""),
        "fixedCost": (entity.get("cost") or {}).get("fixedCost"),
        "brand": str(entity.get("brand") or ""),
        "isEnabled": bool(entity.get("isEnabled", True)),
        "isDisplay": bool(entity.get("isDisplay", True)),
        "bestSeller": bool(entity.get("bestSeller")),
        "newArrival": bool(entity.get("newArrival")),
        "mustTry": bool(entity.get("mustTry")),
    }


def _build_payload(entity_type: str, entity: dict, business: Optional[dict] = None) -> dict:
    if entity_type == "business":
        return _build_business_payload(entity)
    return _build_service_payload(entity, business)


async def handle_delete(event: dict) -> None:
    entity_id = event["entityId"]
    entity_type = event["entityType"]
    await qdrant_db.delete_point(entity_type, entity_id)
    logger.info("Deleted vector %s/%s", entity_type, entity_id)


async def handle_create_update(event: dict) -> None:
    entity_type = event["entityType"]
    entity_id = event["entityId"]
    changed_fields = event.get("changedFields") or []

    entity = await getattr(mongo_db, f"get_{entity_type}")(entity_id)
    if entity is None:
        logger.warning("Entity %s/%s not found in Mongo, skipping", entity_type, entity_id)
        return

    if entity_type == "service" and _should_skip_service(entity):
        logger.debug("Skipping add-on/non-default-variation service %s", entity_id)
        return

    business = None
    if entity_type == "service":
        business_id = str(entity.get("businessId") or "")
        if business_id:
            business = await mongo_db.get_business(business_id)

    resolved = await _resolve_taxonomy(entity_type, entity)
    source_text = build_source_text(entity_type, entity, resolved)
    new_hash = source_hash(source_text)

    existing_point = await qdrant_db.get_point(entity_type, entity_id)
    existing_hash = (existing_point.payload or {}).get("source_hash") if existing_point else None

    now_iso = datetime.now(timezone.utc).isoformat()

    if existing_hash == new_hash:
        payload_update = _build_payload(entity_type, entity, business)
        payload_update["embedding_version"] = EMBEDDING_VERSION
        payload_update["source_hash"] = new_hash
        payload_update["updated_at"] = now_iso
        await qdrant_db.set_payload(entity_type, entity_id, payload_update)
        logger.debug("Payload-only update for %s/%s", entity_type, entity_id)
    else:
        vectors = await embed_texts([source_text])
        vector = vectors[0]
        payload = _build_payload(entity_type, entity, business)
        payload["embedding_version"] = EMBEDDING_VERSION
        payload["source_hash"] = new_hash
        payload["updated_at"] = now_iso
        await qdrant_db.upsert_point(entity_type, entity_id, vector, payload)
        logger.info("Upserted vector for %s/%s", entity_type, entity_id)

    if entity_type == "business" and _business_geo_changed(changed_fields):
        await _fanout_service_geo(entity)


def _business_geo_changed(changed_fields: List[str]) -> bool:
    trigger_fields = {"address"}
    return bool(set(changed_fields) & trigger_fields)


async def _fanout_service_geo(business: dict) -> None:
    business_id = str(business.get("_id", ""))
    loc = (business.get("address") or {}).get("location") or {}
    coords = loc.get("coordinates") or []
    geo = None
    if len(coords) == 2:
        geo = {"lon": float(coords[0]), "lat": float(coords[1])}

    payload_update = {
        "location": geo,
    }
    await qdrant_db.set_payload_by_filter(
        "service",
        [FieldCondition(key="businessId", match=MatchValue(value=business_id))],
        payload_update,
    )
    logger.info("Fanout geo update for business %s services", business_id)


async def process_event(event: dict) -> None:
    doc_id = str(event.get("_id", ""))
    retry_count = int(event.get("retryCount") or 0)
    try:
        if event["operation"] == "DELETE":
            await handle_delete(event)
        else:
            await handle_create_update(event)
        await mongo_db.mark_outbox_done(doc_id)
    except Exception as exc:
        logger.error("Failed to process outbox %s: %s", doc_id, exc)
        await mongo_db.mark_outbox_failed(doc_id, retry_count + 1)


async def poll_outbox() -> None:
    try:
        events = await mongo_db.get_pending_outbox(limit=50)
        if not events:
            return
        logger.debug("Processing %d outbox events", len(events))
        for event in events:
            await process_event(event)
    except Exception as exc:
        logger.error("poll_outbox error: %s", exc)
