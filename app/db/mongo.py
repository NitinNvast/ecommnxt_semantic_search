from __future__ import annotations
from typing import Any, Dict, List, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URL)
    return _client


def get_db():
    return get_client()[settings.MONGODB_DB]


async def ping() -> bool:
    try:
        await get_client().admin.command("ping")
        return True
    except Exception:
        return False


async def get_pending_outbox(limit: int = 50) -> List[Dict]:
    db = get_db()
    # Re-poll FAILED rows too: mark_outbox_failed flips to DEAD at retryCount >= 5,
    # so any row still FAILED has retries left. Without this, a single transient
    # OpenAI/Qdrant blip would strand the event forever.
    cursor = db["embeddingOutbox"].find(
        {"status": {"$in": ["PENDING", "FAILED"]}},
        sort=[("createdAt", 1)],
        limit=limit,
    )
    return await cursor.to_list(length=limit)


async def get_all_entity_ids(collection: str, exclude_addons: bool = False) -> List[str]:
    """All live Mongo _id hex strings for an entity collection (for reconcile)."""
    db = get_db()
    query: Dict[str, Any] = {}
    if exclude_addons:
        query["isAddOn"] = {"$ne": True}
    cursor = db[collection].find(query, projection={"_id": 1})
    docs = await cursor.to_list(length=None)
    return [str(d["_id"]) for d in docs]


async def mark_outbox_done(doc_id: str) -> None:
    db = get_db()
    await db["embeddingOutbox"].update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {"status": "DONE"}},
    )


async def mark_outbox_failed(doc_id: str, retry_count: int) -> None:
    db = get_db()
    new_status = "DEAD" if retry_count >= 5 else "FAILED"
    await db["embeddingOutbox"].update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {"status": new_status, "retryCount": retry_count}},
    )


async def reset_failed_outbox(doc_id: str) -> None:
    db = get_db()
    await db["embeddingOutbox"].update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {"status": "PENDING"}},
    )


async def get_entity(collection: str, entity_id: str) -> Optional[Dict]:
    db = get_db()
    return await db[collection].find_one({"_id": ObjectId(entity_id)})


async def get_business(business_id: str) -> Optional[Dict]:
    return await get_entity("businesses", business_id)


async def get_service(service_id: str) -> Optional[Dict]:
    return await get_entity("services", service_id)


async def text_search_businesses(query: str, limit: int = 40) -> List[Dict]:
    db = get_db()
    cursor = db["businesses"].find(
        {
            "$text": {"$search": query},
            "businessStatus": "APPROVED",
            "availability.status": "ACTIVE",
        },
        projection={"score": {"$meta": "textScore"}, "_id": 1, "businessName": 1},
        sort=[("score", {"$meta": "textScore"})],
        limit=limit,
    )
    return await cursor.to_list(length=limit)


async def text_search_services(query: str, limit: int = 40) -> List[Dict]:
    db = get_db()
    cursor = db["services"].find(
        {
            "$text": {"$search": query},
            "isEnabled": True,
            "isDisplay": True,
            "isAddOn": {"$ne": True},
        },
        projection={"score": {"$meta": "textScore"}, "_id": 1, "service": 1, "businessId": 1},
        sort=[("score", {"$meta": "textScore"})],
        limit=limit,
    )
    return await cursor.to_list(length=limit)


async def hydrate_by_ids(collection: str, ids: List[str]) -> Dict[str, Dict]:
    db = get_db()
    object_ids = [ObjectId(i) for i in ids]
    cursor = db[collection].find({"_id": {"$in": object_ids}})
    docs = await cursor.to_list(length=len(ids))
    return {str(d["_id"]): d for d in docs}


async def get_taxonomy_names(
    collection: str, ids: List[str]
) -> Dict[str, str]:
    """Returns {str(id): name} for a list of taxonomy ObjectIds."""
    if not ids:
        return {}
    db = get_db()
    object_ids = [ObjectId(i) for i in ids if i]
    cursor = db[collection].find({"_id": {"$in": object_ids}}, projection={"name": 1})
    docs = await cursor.to_list(length=len(ids))
    return {str(d["_id"]): d.get("name", "") for d in docs}
