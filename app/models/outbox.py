from __future__ import annotations
from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class OutboxEvent(BaseModel):
    id: str = Field(alias="_id")
    entityType: Literal["service"]
    entityId: str
    operation: Literal["CREATE", "UPDATE", "DELETE"]
    changedFields: List[str] = []
    requiresEmbedding: bool = True
    status: Literal["PENDING", "DONE", "FAILED", "DEAD"] = "PENDING"
    retryCount: int = 0
    createdAt: datetime

    class Config:
        populate_by_name = True
