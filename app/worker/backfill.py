from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple

from app.core.embedder import build_source_text, embed_texts, source_hash
from app.db import node_api
from app.db import qdrant as qdrant_db
from app.worker.outbox_processor import (
    EMBEDDING_VERSION,
    _build_service_payload,
    _resolve_taxonomy,
    _should_skip_service,
)

logger = logging.getLogger(__name__)


async def backfill_services(
    batch_size: int = 100, skip_existing: bool = True
) -> Dict[str, int]:
    """Day-zero backfill: embed every existing service into Qdrant.

    Idempotent when skip_existing=True (only embeds services with no point yet),
    so it is safe to re-run and resumes after an interruption. Embeddings are
    batched (one OpenAI call per ``batch_size`` services) to keep day-zero cost
    and latency low. The text/payload are built with the same helpers as the live
    outbox path, so source_hash matches and the outbox/reconcile won't re-embed.
    """
    all_ids = await node_api.get_all_entity_ids("services", exclude_addons=True)

    existing: Set[str] = set()
    if skip_existing:
        existing = set((await qdrant_db.scroll_all_object_ids("service")).keys())

    pending = [i for i in all_ids if i not in existing]
    stats = {
        "scanned": len(all_ids),
        "embedded": 0,
        "skipped": len(all_ids) - len(pending),
        "failed": 0,
    }

    for start in range(0, len(pending), batch_size):
        batch_ids = pending[start : start + batch_size]
        try:
            await _embed_service_batch(batch_ids, stats)
        except Exception as exc:
            logger.error("backfill: batch at offset %d failed: %s", start, exc)
            stats["failed"] += len(batch_ids)

    logger.info("Service backfill complete: %s", stats)
    return stats


async def _embed_service_batch(batch_ids: List[str], stats: Dict[str, int]) -> None:
    docs = await node_api.hydrate_by_ids("services", batch_ids)

    prepared: List[Tuple[str, dict, str]] = []  # (entity_id, doc, source_text)
    for entity_id in batch_ids:
        doc = docs.get(entity_id)
        if doc is None or _should_skip_service(doc):
            stats["skipped"] += 1
            continue
        resolved = await _resolve_taxonomy("service", doc)
        text = build_source_text("service", doc, resolved)
        prepared.append((entity_id, doc, text))

    if not prepared:
        return

    vectors = await embed_texts([text for _, _, text in prepared])
    now_iso = datetime.now(timezone.utc).isoformat()

    points: List[Tuple[str, List[float], dict]] = []
    for (entity_id, doc, text), vector in zip(prepared, vectors):
        payload = _build_service_payload(doc)
        payload["source_text"] = text
        payload["embedding_version"] = EMBEDDING_VERSION
        payload["source_hash"] = source_hash(text)
        payload["updated_at"] = now_iso
        points.append((entity_id, vector, payload))

    await qdrant_db.bulk_upsert_points("service", points)
    stats["embedded"] += len(points)
