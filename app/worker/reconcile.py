from __future__ import annotations
import logging
from typing import Dict, List

from app.db import mongo as mongo_db
from app.db import qdrant as qdrant_db
from app.worker.outbox_processor import ENTITY_COLLECTION_MAP, handle_create_update

logger = logging.getLogger(__name__)


async def reconcile_entity(entity_type: str) -> Dict:
    """Diff live Mongo _ids against Qdrant points: repair missing, delete orphans.

    This is the eventual-consistency safety net for any dropped outbox event or
    write path that bypassed the Mongoose hooks (bulkWrite, native ops, crashes).
    """
    collection = ENTITY_COLLECTION_MAP[entity_type]
    mongo_ids = set(
        await mongo_db.get_all_entity_ids(
            collection, exclude_addons=(entity_type == "service")
        )
    )
    qdrant_map = await qdrant_db.scroll_all_mongo_ids(entity_type)
    qdrant_ids = set(qdrant_map.keys())

    missing = mongo_ids - qdrant_ids
    orphaned = qdrant_ids - mongo_ids

    for mid in missing:
        try:
            await handle_create_update(
                {
                    "entityType": entity_type,
                    "entityId": mid,
                    "operation": "UPDATE",
                    "changedFields": [],
                }
            )
        except Exception as exc:
            logger.error("reconcile: failed to repair %s/%s: %s", entity_type, mid, exc)

    for mid in orphaned:
        try:
            await qdrant_db.delete_point(entity_type, mid)
        except Exception as exc:
            logger.error(
                "reconcile: failed to delete orphan %s/%s: %s", entity_type, mid, exc
            )

    logger.info(
        "Reconcile %s: %d missing repaired, %d orphans deleted",
        entity_type,
        len(missing),
        len(orphaned),
    )
    return {"entity_type": entity_type, "missing": len(missing), "orphaned": len(orphaned)}


async def reconcile_all() -> List[Dict]:
    results = []
    for entity_type in ("business", "service"):
        try:
            results.append(await reconcile_entity(entity_type))
        except Exception as exc:
            logger.error("reconcile_all: %s failed: %s", entity_type, exc)
    return results
