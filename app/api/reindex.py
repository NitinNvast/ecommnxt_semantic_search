import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from app.config import settings
from app.core.embedder import SEMANTIC_FIELDS
from app.db import node_api
from app.db import qdrant as qdrant_db
from app.models.search import EmbeddingStatusResponse, JobResponse, ReindexRequest
from app.worker.outbox_processor import handle_create_update

router = APIRouter()


def _require_internal_key(x_internal_key: str = Header(default=None)) -> None:
    if not x_internal_key or x_internal_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


async def _enqueue_single_reindex(entity_type: str, entity_id: str) -> str:
    event = {
        "_id": str(uuid.uuid4()),
        "entityType": entity_type,
        "entityId": entity_id,
        "operation": "UPDATE",
        "changedFields": list(SEMANTIC_FIELDS.get(entity_type, set())),
        "requiresEmbedding": True,
        "status": "PENDING",
        "retryCount": 0,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await handle_create_update(event)
    return str(uuid.uuid4())


@router.post("/reindex/{entity_type}/{entity_id}", response_model=JobResponse)
async def reindex_single(
    entity_type: Literal["service"],
    entity_id: str,
    background_tasks: BackgroundTasks,
    _key: None = Depends(_require_internal_key),
) -> JobResponse:
    background_tasks.add_task(_enqueue_single_reindex, entity_type, entity_id)
    return JobResponse(
        jobId=str(uuid.uuid4()),
        message=f"Re-index queued for {entity_type}/{entity_id}",
    )


@router.post("/reindex/business/{business_id}/services", response_model=JobResponse)
async def reindex_business_services(
    business_id: str,
    background_tasks: BackgroundTasks,
    _key: None = Depends(_require_internal_key),
) -> JobResponse:
    async def _fanout():
        service_ids = await node_api.get_all_entity_ids("services", business_id=business_id)
        for svc_id in service_ids:
            await _enqueue_single_reindex("service", svc_id)

    background_tasks.add_task(_fanout)
    return JobResponse(
        jobId=str(uuid.uuid4()),
        message=f"Fan-out reindex queued for business {business_id}",
    )


@router.post("/bulk-reindex", response_model=JobResponse)
async def bulk_reindex(
    request: ReindexRequest,
    background_tasks: BackgroundTasks,
    _key: None = Depends(_require_internal_key),
) -> JobResponse:
    async def _bulk():
        ids = await node_api.get_all_entity_ids("services")
        for eid in ids:
            await _enqueue_single_reindex("service", eid)

    background_tasks.add_task(_bulk)
    return JobResponse(
        jobId=str(uuid.uuid4()),
        message=f"Bulk reindex queued for {request.entity} — {request.reason}",
    )


@router.get("/embedding-status/{entity_type}/{entity_id}", response_model=EmbeddingStatusResponse)
async def embedding_status(
    entity_type: Literal["service"],
    entity_id: str,
    _key: None = Depends(_require_internal_key),
) -> EmbeddingStatusResponse:
    point = await qdrant_db.get_point(entity_type, entity_id)
    if not point:
        return EmbeddingStatusResponse(exists=False, inSync=False)
    payload = point.payload or {}
    return EmbeddingStatusResponse(
        exists=True,
        embedding_version=payload.get("embedding_version"),
        source_hash=payload.get("source_hash"),
        updated_at=payload.get("updated_at"),
        inSync=True,
    )
