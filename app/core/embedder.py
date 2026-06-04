from __future__ import annotations
import hashlib
import re
from typing import Dict, List, Optional
from openai import AsyncOpenAI
from app.config import settings
from app.db import redis as redis_db

SEMANTIC_FIELDS: Dict[str, frozenset] = {
    "business": frozenset([
        "businessName", "description", "amenities",
        "category", "subCategories", "brandIds",
    ]),
    "service": frozenset([
        "service", "description", "productDetailDescription",
        "brand", "countryOfOrigin", "subcategory",
    ]),
}

_openai: Optional[AsyncOpenAI] = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai


def _clean(text: object, max_chars: int = 1000) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    if s.lower() in ("", "na", "n/a", "null", "none", "blank"):
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_chars]


def build_business_text(entity: dict, resolved: Optional[dict] = None) -> str:
    r = resolved or {}
    parts = [
        _clean(entity.get("businessName")),
        " ".join(filter(None, [
            r.get("category_name", ""),
            " ".join(r.get("subcategory_names", [])),
        ])),
        " ".join(filter(None, r.get("brand_names", []))),
        _clean(entity.get("description")),
        _clean(entity.get("amenities")),
    ]
    return "\n".join(p for p in parts if p)


def build_service_text(entity: dict, resolved: Optional[dict] = None) -> str:
    r = resolved or {}
    detail_parts: List[str] = []
    for section in entity.get("productDetailDescription", []):
        for item in section.get("items", []):
            label = _clean(item.get("label"))
            value = _clean(item.get("value"))
            if label and value:
                detail_parts.append(f"{label}: {value}")
    parts = [
        _clean(entity.get("service")),
        r.get("category_name", ""),
        " ".join(filter(None, [r.get("brand_name", ""), r.get("country_name", "")])),
        _clean(entity.get("description")),
        "; ".join(detail_parts)[:500],
    ]
    return "\n".join(p for p in parts if p)


def build_source_text(entity_type: str, entity: dict, resolved: Optional[dict] = None) -> str:
    if entity_type == "business":
        return build_business_text(entity, resolved)
    if entity_type == "service":
        return build_service_text(entity, resolved)
    raise ValueError(f"Unknown entity_type: {entity_type}")


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def is_semantic_field_changed(entity_type: str, changed_fields: List[str]) -> bool:
    semantic = SEMANTIC_FIELDS.get(entity_type, frozenset())
    return bool(set(changed_fields) & semantic)


async def embed_texts(texts: List[str]) -> List[List[float]]:
    response = await _get_openai().embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


async def embed_query(normalized_query: str) -> List[float]:
    key = source_hash(normalized_query)
    cached = await redis_db.get_vector(key)
    if cached is not None:
        return cached
    vectors = await embed_texts([normalized_query])
    vector = vectors[0]
    await redis_db.set_vector(key, vector)
    return vector
