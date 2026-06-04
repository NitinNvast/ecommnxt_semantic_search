from __future__ import annotations
import json
from typing import List, Optional
import redis.asyncio as aioredis
from app.config import settings

_client: Optional[aioredis.Redis] = None
_VECTOR_TTL = 7 * 24 * 3600  # 7 days


def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
        )
    return _client


async def ping() -> bool:
    try:
        return await get_client().ping()
    except Exception:
        return False


async def get_vector(cache_key: str) -> Optional[List[float]]:
    raw = await get_client().get(f"emb:{cache_key}")
    if raw is None:
        return None
    return json.loads(raw)


async def set_vector(cache_key: str, vector: List[float]) -> None:
    await get_client().setex(
        f"emb:{cache_key}",
        _VECTOR_TTL,
        json.dumps(vector),
    )
