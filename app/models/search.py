from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    entities: List[Literal["service"]] = ["service"]
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class SearchResult(BaseModel):
    entityType: str
    id: str
    serviceId: str = ""


class SearchResponse(BaseModel):
    results: List[SearchResult]


class EmbeddingStatusResponse(BaseModel):
    exists: bool
    embedding_version: Optional[str] = None
    source_hash: Optional[str] = None
    updated_at: Optional[str] = None
    inSync: bool = False


class ReindexRequest(BaseModel):
    entity: Literal["service"]
    filter: Dict[str, Any] = {}
    reason: str = ""


class JobResponse(BaseModel):
    jobId: str
    message: str = ""
