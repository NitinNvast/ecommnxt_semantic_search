# web/semantic-search/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    NODE_API_URL: str
    NODE_SERVICE_TOKEN: str
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    OPENAI_API_KEY: str
    JWT_SECRET: str
    INTERNAL_API_KEY: str
    OUTBOX_POLL_INTERVAL: int = 5
    RECONCILE_HOUR: int = 3  # hour-of-day (server TZ) for the nightly reconcile job
    EMBEDDING_BATCH_SIZE: int = 96
    LOG_LEVEL: str = "INFO"
    SERVICE_PORT: int = 8001

    class Config:
        env_file = ".env"


settings = Settings()
