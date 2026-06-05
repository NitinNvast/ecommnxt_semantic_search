import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mocks(mocker):
    mongo = MagicMock()
    # Mongo has A and B
    mongo.get_all_entity_ids = AsyncMock(return_value=["A", "B"])
    qdrant = MagicMock()
    # Qdrant has B and C (so A is missing, C is orphaned)
    qdrant.scroll_all_object_ids = AsyncMock(return_value={"B": "uuid-b", "C": "uuid-c"})
    qdrant.delete_point = AsyncMock()
    handle = AsyncMock()
    mocker.patch("app.worker.reconcile.mongo_db", mongo)
    mocker.patch("app.worker.reconcile.qdrant_db", qdrant)
    mocker.patch("app.worker.reconcile.handle_create_update", handle)
    return mongo, qdrant, handle


class TestReconcileEntity:
    async def test_missing_vectors_are_repaired(self, mocks):
        _, _, handle = mocks
        from app.worker.reconcile import reconcile_entity
        await reconcile_entity("business")
        # A exists in Mongo but not Qdrant -> must be re-embedded.
        handle.assert_awaited_once()
        event = handle.await_args[0][0]
        assert event["entityId"] == "A"
        assert event["entityType"] == "business"

    async def test_orphaned_vectors_are_deleted(self, mocks):
        _, qdrant, _ = mocks
        from app.worker.reconcile import reconcile_entity
        await reconcile_entity("business")
        # C exists in Qdrant but not Mongo -> must be deleted.
        qdrant.delete_point.assert_awaited_once_with("business", "C")

    async def test_returns_counts(self, mocks):
        from app.worker.reconcile import reconcile_entity
        result = await reconcile_entity("business")
        assert result["missing"] == 1
        assert result["orphaned"] == 1
