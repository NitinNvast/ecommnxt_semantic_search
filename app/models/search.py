from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class GeoFilter(BaseModel):
    lat: float
    lng: float
    radiusKm: float = 5.0


class SearchFilters(BaseModel):
    category: Optional[str] = None
    priceMax: Optional[float] = None
    serviceModes: Optional[List[str]] = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    entities: List[Literal["business", "service"]] = ["business", "service"]
    geo: Optional[GeoFilter] = None
    filters: Optional[SearchFilters] = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class BusinessSummary(BaseModel):
    id: str
    name: str
    rating: float
    xirifyAssured: bool


class ResultHighlight(BaseModel):
    name: str
    price: Optional[float] = None
    description: Optional[str] = None


class SearchResult(BaseModel):
    entityType: str
    id: str
    score: float
    distanceKm: Optional[float] = None
    business: Optional[BusinessSummary] = None
    highlight: ResultHighlight


class SearchResponse(BaseModel):
    results: List[SearchResult]
    fallbackUsed: bool = False
    total: int
    tookMs: int


class EmbeddingStatusResponse(BaseModel):
    exists: bool
    embedding_version: Optional[str] = None
    source_hash: Optional[str] = None
    updated_at: Optional[str] = None
    inSync: bool = False


class ReindexRequest(BaseModel):
    entity: Literal["business", "service"]
    filter: Dict[str, Any] = {}
    reason: str = ""


class JobResponse(BaseModel):
    jobId: str
    message: str = ""
