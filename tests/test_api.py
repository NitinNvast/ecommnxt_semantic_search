import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client():
    with (
        patch("app.db.qdrant.ensure_collections", AsyncMock()),
        patch("app.worker.scheduler.start_scheduler"),
        patch("app.worker.scheduler.stop_scheduler"),
    ):
        from app.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


class TestHealth:
    async def test_health_returns_200(self, client):
        with (
            patch("app.db.mongo.ping", AsyncMock(return_value=True)),
            patch("app.db.qdrant.ping", AsyncMock(return_value=True)),
            patch("app.db.redis.ping", AsyncMock(return_value=True)),
            patch("app.db.mongo.get_db") as mock_db,
        ):
            mock_db.return_value.__getitem__.return_value.count_documents = AsyncMock(return_value=0)
            response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "mongo" in data
        assert "qdrant" in data
        assert "redis" in data


from jose import jwt as jose_jwt


def make_token(secret: str = "test-secret") -> str:
    return jose_jwt.encode(
        {"sub": "consumer123", "role": "consumer"},
        secret,
        algorithm="HS256",
    )


class TestSearchEndpoint:
    async def test_returns_401_without_jwt(self, client):
        response = await client.post(
            "/search",
            json={"query": "biryani"},
        )
        assert response.status_code == 401

    async def test_returns_422_with_empty_query(self, client):
        token = make_token()
        response = await client.post(
            "/search",
            json={"query": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_returns_200_with_valid_request(self, client):
        from app.models.search import SearchResponse
        token = make_token()
        mock_resp = SearchResponse(results=[], fallbackUsed=False, total=0, tookMs=5)
        with patch(
            "app.api.search.search_engine.search",
            AsyncMock(return_value=mock_resp),
        ):
            response = await client.post(
                "/search",
                json={"query": "biryani"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "tookMs" in data


class TestReindexEndpoints:
    async def test_reindex_single_returns_403_without_internal_key(self, client):
        response = await client.post("/internal/reindex/business/abc123")
        assert response.status_code == 403

    async def test_reindex_single_returns_200_with_correct_key(self, client):
        with patch(
            "app.api.reindex._enqueue_single_reindex", AsyncMock(return_value="job-1")
        ):
            response = await client.post(
                "/internal/reindex/business/abc123",
                headers={"X-Internal-Key": "test-internal-key"},
            )
        assert response.status_code == 200
        assert "jobId" in response.json()

    async def test_embedding_status_returns_403_without_key(self, client):
        response = await client.get("/internal/embedding-status/business/abc123")
        assert response.status_code == 403

    async def test_embedding_status_returns_200_with_key(self, client):
        with patch(
            "app.api.reindex.qdrant_db.get_point",
            AsyncMock(return_value=None),
        ):
            response = await client.get(
                "/internal/embedding-status/business/abc123",
                headers={"X-Internal-Key": "test-internal-key"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is False
