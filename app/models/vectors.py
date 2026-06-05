from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel


class GeoPoint(BaseModel):
    lon: float
    lat: float


class ServicePayload(BaseModel):
    entity_type: str = "service"
    businessId: str
    serviceId:str
    objectId: str
    price: Optional[float] = None
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
