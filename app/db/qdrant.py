from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    GeoPoint,
    GeoRadius,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    VectorParams,
)
from app.config import settings

COLLECTIONS = {
    "business": "business_vectors",
    "service": "service_vectors",
}

_client: Optional[AsyncQdrantClient] = None

# Fixed namespace for deriving Qdrant point ids from Mongo ObjectIds.
# Qdrant only accepts an unsigned int or a UUID as a point id — a raw 24-char
# ObjectId hex is rejected — so we map each Mongo _id to a deterministic UUID5.
# The real Mongo _id is preserved in payload["mongoId"] for hydration.
_POINT_NAMESPACE = uuid.UUID("b6e9a0c2-7f3d-5a1e-9c4b-2d8f0a1e3c5d")


def to_point_id(entity_id: str) -> str:
    """Deterministically map a Mongo _id (hex string) to a Qdrant-valid UUID."""
    return str(uuid.uuid5(_POINT_NAMESPACE, str(entity_id)))


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.QDRANT_HOST, port=settings.QDRANT_PORT
        )
    return _client


async def ping() -> bool:
    try:
        await get_client().get_collections()
        return True
    except Exception:
        return False


async def ensure_collections() -> None:
    client = get_client()
    existing = {c.name for c in (await client.get_collections()).collections}

    for collection_name in COLLECTIONS.values():
        if collection_name in existing:
            continue
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
        )
        for field, schema in [
            ("businessId", PayloadSchemaType.KEYWORD),
            ("businessStatus", PayloadSchemaType.KEYWORD),
            ("isAvailable", PayloadSchemaType.BOOL),
            ("isEnabled", PayloadSchemaType.BOOL),
            ("isDisplay", PayloadSchemaType.BOOL),
            ("location", PayloadSchemaType.GEO),
        ]:
            try:
                await client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception:
                pass


async def upsert_point(
    entity_type: str,
    point_id: str,
    vector: List[float],
    payload: Dict[str, Any],
) -> None:
    collection = COLLECTIONS[entity_type]
    await get_client().upsert(
        collection_name=collection,
        points=[PointStruct(id=to_point_id(point_id), vector=vector, payload=payload)],
    )


async def set_payload(
    entity_type: str,
    point_id: str,
    payload: Dict[str, Any],
) -> None:
    collection = COLLECTIONS[entity_type]
    await get_client().set_payload(
        collection_name=collection,
        payload=payload,
        points=[to_point_id(point_id)],
    )


async def set_payload_by_filter(
    entity_type: str,
    must_conditions: List[FieldCondition],
    payload: Dict[str, Any],
) -> None:
    collection = COLLECTIONS[entity_type]
    await get_client().set_payload(
        collection_name=collection,
        payload=payload,
        points=Filter(must=must_conditions),
    )


async def delete_point(entity_type: str, point_id: str) -> None:
    collection = COLLECTIONS[entity_type]
    await get_client().delete(
        collection_name=collection,
        points_selector=PointIdsList(points=[to_point_id(point_id)]),
    )


async def search_vectors(
    entity_type: str,
    vector: List[float],
    must_conditions: List[FieldCondition],
    limit: int = 40,
) -> List[Any]:
    collection = COLLECTIONS[entity_type]
    response = await get_client().query_points(
        collection_name=collection,
        query=vector,
        query_filter=Filter(must=must_conditions),
        limit=limit,
        with_payload=True,
    )
    return response.points


async def get_point(entity_type: str, point_id: str) -> Optional[Any]:
    collection = COLLECTIONS[entity_type]
    results = await get_client().retrieve(
        collection_name=collection,
        ids=[to_point_id(point_id)],
        with_payload=True,
    )
    return results[0] if results else None


async def bulk_upsert_points(
    entity_type: str,
    points: list,
) -> None:
    """Upsert a batch of (entity_id, vector, payload) tuples in one call."""
    collection = COLLECTIONS[entity_type]
    structs = [
        PointStruct(id=to_point_id(eid), vector=vec, payload=payload)
        for eid, vec, payload in points
    ]
    await get_client().upsert(collection_name=collection, points=structs)


async def scroll_all_object_ids(entity_type: str, batch: int = 1000) -> Dict[str, str]:
    """Return {objectId: point_id} for every point in the collection (for reconcile)."""
    collection = COLLECTIONS[entity_type]
    client = get_client()
    result: Dict[str, str] = {}
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=collection,
            limit=batch,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            object_id = (p.payload or {}).get("mongoId")
            if object_id:
                result[str(object_id)] = str(p.id)
        if offset is None:
            break
    return result


def build_geo_condition(lat: float, lng: float, radius_km: float) -> FieldCondition:
    return FieldCondition(
        key="location",
        geo_radius=GeoRadius(
            center=GeoPoint(lat=lat, lon=lng),
            radius=radius_km * 1000,
        ),
    )
