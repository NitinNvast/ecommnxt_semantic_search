from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class ServicePayload(BaseModel):
    entity_type: str = "service"
    mongoId: str          # Mongo _id
    serviceId: str
    fixedCost: Optional[float] = None   # Cost.fixedCost
    embedding_version: str = "v1-te3s"
    source_hash: str = ""
    updated_at: str = ""
