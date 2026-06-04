import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


SAMPLE_BUSINESS_DOC = {
    "_id": "663aaa000000000000000001",
    "businessName": "Spice Garden",
    "description": "Best Indian food",
    "availability": {"status": "ACTIVE"},
    "businessStatus": "APPROVED",
    "address": {"location": {"coordinates": [73.85, 18.52]}},
    "overallRating": 4.5,
    "sortOrder": 10,
    "xirifyAssured": True,
}

SAMPLE_SERVICE_DOC = {
    "_id": "663aaa000000000000000002",
    "service": "Paneer Tikka",
    "description": "Grilled paneer",
    "businessId": "663aaa000000000000000003",
    "isEnabled": True,
    "isDisplay": True,
    "isAddOn": False,
    "isDefaultVariationView": True,
}

PENDING_BUSINESS_CREATE = {
    "_id": "outbox001",
    "entityType": "business",
    "entityId": "663aaa000000000000000001",
    "operation": "CREATE",
    "changedFields": [],
    "requiresEmbedding": True,
    "status": "PENDING",
    "retryCount": 0,
    "createdAt": "2026-05-29T10:00:00",
}

PENDING_SERVICE_UPDATE_VOLATILE = {
    "_id": "outbox002",
    "entityType": "service",
    "entityId": "663aaa000000000000000002",
    "operation": "UPDATE",
    "changedFields": ["cost", "isEnabled"],
    "requiresEmbedding": False,
    "status": "PENDING",
    "retryCount": 0,
    "createdAt": "2026-05-29T10:01:00",
}

PENDING_DELETE = {
    "_id": "outbox003",
    "entityType": "service",
    "entityId": "663aaa000000000000000002",
    "operation": "DELETE",
    "changedFields": [],
    "requiresEmbedding": False,
    "status": "PENDING",
    "retryCount": 0,
    "createdAt": "2026-05-29T10:02:00",
}


@pytest.fixture
def mock_mongo(mocker):
    m = MagicMock()
    m.get_pending_outbox = AsyncMock()
    m.mark_outbox_done = AsyncMock()
    m.mark_outbox_failed = AsyncMock()
    m.get_business = AsyncMock(return_value=SAMPLE_BUSINESS_DOC)
    m.get_service = AsyncMock(return_value=SAMPLE_SERVICE_DOC)
    m.get_taxonomy_names = AsyncMock(return_value={})
    mocker.patch("app.worker.outbox_processor.mongo_db", m)
    return m


@pytest.fixture
def mock_qdrant(mocker):
    q = MagicMock()
    q.upsert_point = AsyncMock()
    q.set_payload = AsyncMock()
    q.set_payload_by_filter = AsyncMock()
    q.delete_point = AsyncMock()
    q.get_point = AsyncMock(return_value=None)
    mocker.patch("app.worker.outbox_processor.qdrant_db", q)
    return q


@pytest.fixture
def mock_embed(mocker):
    mocker.patch(
        "app.worker.outbox_processor.embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    )


class TestProcessDeleteEvent:
    async def test_delete_calls_qdrant_delete(self, mock_mongo, mock_qdrant, mock_embed):
        from app.worker.outbox_processor import process_event
        await process_event(PENDING_DELETE)
        mock_qdrant.delete_point.assert_called_once_with(
            "service", "663aaa000000000000000002"
        )

    async def test_delete_marks_outbox_done(self, mock_mongo, mock_qdrant, mock_embed):
        from app.worker.outbox_processor import process_event
        await process_event(PENDING_DELETE)
        mock_mongo.mark_outbox_done.assert_called_once_with("outbox003")


class TestProcessCreateEvent:
    async def test_create_calls_upsert(self, mock_mongo, mock_qdrant, mock_embed):
        from app.worker.outbox_processor import process_event
        await process_event(PENDING_BUSINESS_CREATE)
        mock_qdrant.upsert_point.assert_called_once()
        call_args = mock_qdrant.upsert_point.call_args
        assert call_args[0][0] == "business"
        assert len(call_args[0][2]) == 1536

    async def test_create_marks_outbox_done(self, mock_mongo, mock_qdrant, mock_embed):
        from app.worker.outbox_processor import process_event
        await process_event(PENDING_BUSINESS_CREATE)
        mock_mongo.mark_outbox_done.assert_called_once_with("outbox001")


class TestProcessUpdateVolatileOnly:
    async def test_volatile_only_update_skips_openai_uses_set_payload(
        self, mock_mongo, mock_qdrant, mocker
    ):
        embed_mock = mocker.patch(
            "app.worker.outbox_processor.embed_texts", AsyncMock()
        )
        existing_point = MagicMock()
        existing_point.payload = {
            "source_hash": "will_match",
            "embedding_version": "v1-te3s",
        }
        mock_qdrant.get_point = AsyncMock(return_value=existing_point)

        mocker.patch(
            "app.worker.outbox_processor.source_hash",
            return_value="will_match",
        )

        from app.worker.outbox_processor import process_event
        await process_event(PENDING_SERVICE_UPDATE_VOLATILE)

        embed_mock.assert_not_called()
        mock_qdrant.set_payload.assert_called_once()


class TestRetryAndDeadLetter:
    async def test_failed_event_increments_retry_count(
        self, mock_mongo, mock_qdrant, mocker
    ):
        mock_qdrant.upsert_point = AsyncMock(side_effect=Exception("Qdrant down"))
        mocker.patch(
            "app.worker.outbox_processor.embed_texts",
            AsyncMock(return_value=[[0.1] * 1536]),
        )
        from app.worker.outbox_processor import process_event
        await process_event(PENDING_BUSINESS_CREATE)
        mock_mongo.mark_outbox_failed.assert_called_once_with("outbox001", 1)

    async def test_retry_count_5_marks_dead(self, mock_mongo, mock_qdrant, mocker):
        dead_event = {**PENDING_BUSINESS_CREATE, "retryCount": 5}
        mock_qdrant.upsert_point = AsyncMock(side_effect=Exception("Still down"))
        mocker.patch(
            "app.worker.outbox_processor.embed_texts",
            AsyncMock(return_value=[[0.1] * 1536]),
        )
        from app.worker.outbox_processor import process_event
        await process_event(dead_event)
        mock_mongo.mark_outbox_failed.assert_called_once_with("outbox001", 6)
