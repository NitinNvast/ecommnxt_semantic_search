from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from app.config import settings
from app.core import search_engine
from app.models.search import SearchRequest, SearchResponse

router = APIRouter()


def _verify_jwt(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    _token: dict = Depends(_verify_jwt),
) -> SearchResponse:
    return await search_engine.search(request)
