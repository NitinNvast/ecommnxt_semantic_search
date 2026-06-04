import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.db import qdrant as qdrant_db
from app.worker.scheduler import start_scheduler, stop_scheduler
from app.api import health, search, reindex

logging.basicConfig(level=settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await qdrant_db.ensure_collections()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Xirify Semantic Search",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health.router, tags=["health"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(reindex.router, prefix="/internal", tags=["internal"])
