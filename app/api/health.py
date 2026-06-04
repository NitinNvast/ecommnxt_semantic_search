from fastapi import APIRouter
from app.db import mongo as mongo_db
from app.db import qdrant as qdrant_db
from app.db import redis as redis_db

router = APIRouter()


@router.get("/health")
async def health():
    mongo_ok = await mongo_db.ping()
    qdrant_ok = await qdrant_db.ping()
    redis_ok = await redis_db.ping()

    queue_depth = None
    dead_count = None
    if mongo_ok:
        db = mongo_db.get_db()
        queue_depth = await db["embeddingOutbox"].count_documents({"status": "PENDING"})
        dead_count = await db["embeddingOutbox"].count_documents({"status": "DEAD"})

    return {
        "status": "ok" if (mongo_ok and qdrant_ok and redis_ok) else "degraded",
        "mongo": "ok" if mongo_ok else "error",
        "qdrant": "ok" if qdrant_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "queueDepth": queue_depth,
        "deadLetterCount": dead_count,
    }
