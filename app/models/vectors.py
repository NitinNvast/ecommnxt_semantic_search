from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel


class GeoPoint(BaseModel):
    lon: float
    lat: float


class BusinessPayload(BaseModel):
    entity_type: str = "business"
    businessId: str
    location: Optional[GeoPoint] = None
    categoryType: Optional[str] = None
    category: Optional[str] = None
    serviceModes: List[str] = []
    businessStatus: str = "APPROVED"
    isAvailable: bool = True
    overallRating: float = 0.0
    uniqueReviewsCount: int = 0
    xirifyAssured: bool = False
    topRated: bool = False
    popular: bool = False
    isnew: bool = False
    sortOrder: int = 40
    serviceableArea: float = 5.0
    embedding_version: str = "v1-te3s"
    source_hash: str = ""
    updated_at: str = ""


class ServicePayload(BaseModel):
    entity_type: str = "service"
    businessId: str
    location: Optional[GeoPoint] = None
    subcategory: Optional[str] = None
    fixedCost: Optional[float] = None
    brand: Optional[str] = None
    isEnabled: bool = True
    isDisplay: bool = True
    bestSeller: bool = False
    newArrival: bool = False
    mustTry: bool = False
    embedding_version: str = "v1-te3s"
    source_hash: str = ""
    updated_at: str = ""
