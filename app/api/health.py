from fastapi import APIRouter
from app.db import node_api
from app.db import qdrant as qdrant_db
from app.db import redis as redis_db

router = APIRouter()


@router.get("/health")
async def health():
    node_ok = await node_api.ping()
    qdrant_ok = await qdrant_db.ping()
    redis_ok = await redis_db.ping()

    queue_depth = None
    dead_count = None
    if node_ok:
        try:
            stats = await node_api.outbox_stats()
            queue_depth = stats.get("queueDepth")
            dead_count = stats.get("deadLettered")
        except Exception:
            pass

    return {
        "status": "ok" if (node_ok and qdrant_ok and redis_ok) else "degraded",
        "nodeApi": "ok" if node_ok else "error",
        "qdrant": "ok" if qdrant_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "queueDepth": queue_depth,
        "deadLetterCount": dead_count,
    }
