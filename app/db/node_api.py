from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


def _base() -> str:
    return settings.NODE_API_URL.rstrip("/")


def _headers() -> Dict[str, str]:
    return {"x-service-token": settings.NODE_SERVICE_TOKEN}


async def ping() -> bool:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_base()}/api/semantic/outbox/stats", headers=_headers())
            return r.status_code == 200
    except Exception:
        return False


async def outbox_stats() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}/api/semantic/outbox/stats", headers=_headers())
        r.raise_for_status()
        return r.json()


async def claim_outbox(limit: int = 50) -> List[Dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{_base()}/api/semantic/outbox/claim",
            json={"limit": limit},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("documents", [])


async def mark_outbox_done(doc_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{_base()}/api/semantic/outbox/ack",
            json={"ids": [doc_id]},
            headers=_headers(),
        )
        r.raise_for_status()


async def mark_outbox_failed(doc_id: str, retry_count: int = 0) -> None:
    # retry_count is unused — Node manages MAX_ATTEMPTS internally
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{_base()}/api/semantic/outbox/fail",
            json={"ids": [doc_id]},
            headers=_headers(),
        )
        r.raise_for_status()


async def get_service(service_id: str) -> Optional[Dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_base()}/api/semantic/internal/services/{service_id}",
            headers=_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def get_business(business_id: str) -> Optional[Dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_base()}/api/semantic/internal/businesses/{business_id}",
            headers=_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def get_all_entity_ids(
    collection: str,
    exclude_addons: bool = False,
    business_id: Optional[str] = None,
) -> List[str]:
    params: Dict[str, str] = {}
    if exclude_addons:
        params["excludeAddons"] = "true"
    if business_id:
        params["businessId"] = business_id

    if collection == "services":
        url = f"{_base()}/api/semantic/internal/services/ids"
    else:
        url = f"{_base()}/api/semantic/internal/businesses/ids"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, params=params, headers=_headers())
        r.raise_for_status()
        return r.json().get("ids", [])


async def hydrate_by_ids(collection: str, ids: List[str]) -> Dict[str, Dict]:
    if not ids:
        return {}
    if collection == "services":
        fetch = get_service
    else:
        fetch = get_business

    async def _fetch(eid: str) -> Optional[tuple]:
        doc = await fetch(eid)
        return (eid, doc) if doc is not None else None

    results = await asyncio.gather(*[_fetch(i) for i in ids])
    return {pair[0]: pair[1] for pair in results if pair is not None}


async def get_taxonomy_names(collection: str, ids: List[str]) -> Dict[str, str]:
    if not ids:
        return {}
    resp_ids = ",".join(str(i) for i in ids)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_base()}/api/semantic/internal/taxonomy/{collection}",
            params={"ids": resp_ids},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


async def text_search_businesses(query: str, limit: int = 40) -> List[Dict]:
    return []


async def text_search_services(query: str, limit: int = 40) -> List[Dict]:
    return []


async def get_pending_outbox(limit: int = 50) -> List[Dict]:
    return await claim_outbox(limit)
