import pytest
from unittest.mock import AsyncMock, MagicMock


def _svc(_id, **extra):
    return {"_id": _id, "service": f"svc-{_id}", "cost": {"fixedCost": 10}, **extra}


@pytest.fixture
def mocks(mocker):
    mongo = MagicMock()
    mongo.get_all_entity_ids = AsyncMock()
    mongo.hydrate_by_ids = AsyncMock()
    mocker.patch("app.worker.backfill.node_api", mongo)

    qdrant = MagicMock()
    qdrant.scroll_all_object_ids = AsyncMock(return_value={})
    qdrant.bulk_upsert_points = AsyncMock()
    mocker.patch("app.worker.backfill.qdrant_db", qdrant)

    embed = mocker.patch(
        "app.worker.backfill.embed_texts",
        AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts]),
    )
    # No-op taxonomy resolution so we don't reach Mongo for subcategory names.
    mocker.patch("app.worker.backfill._resolve_taxonomy", AsyncMock(return_value={}))

    return mongo, qdrant, embed


class TestBackfillServices:
    async def test_embeds_all_when_qdrant_empty(self, mocks):
        mongo, qdrant, embed = mocks
        ids = ["a", "b", "c"]
        mongo.get_all_entity_ids.return_value = ids
        mongo.hydrate_by_ids.return_value = {i: _svc(i) for i in ids}

        from app.worker.backfill import backfill_services
        stats = await backfill_services(batch_size=100)

        assert stats == {"scanned": 3, "embedded": 3, "skipped": 0, "failed": 0}
        qdrant.bulk_upsert_points.assert_called_once()
        # one batched OpenAI call for the 3 texts
        assert embed.call_count == 1
        assert len(embed.call_args[0][0]) == 3

    async def test_skips_already_embedded(self, mocks):
        mongo, qdrant, embed = mocks
        ids = ["a", "b", "c"]
        mongo.get_all_entity_ids.return_value = ids
        qdrant.scroll_all_object_ids.return_value = {"a": "uuid-a"}  # already in Qdrant
        mongo.hydrate_by_ids.return_value = {"b": _svc("b"), "c": _svc("c")}

        from app.worker.backfill import backfill_services
        stats = await backfill_services(batch_size=100)

        assert stats["scanned"] == 3
        assert stats["skipped"] == 1
        assert stats["embedded"] == 2
        # only the pending ids were hydrated
        assert sorted(mongo.hydrate_by_ids.call_args[0][1]) == ["b", "c"]

    async def test_batches_embed_calls(self, mocks):
        mongo, qdrant, embed = mocks
        ids = [str(i) for i in range(5)]
        mongo.get_all_entity_ids.return_value = ids
        mongo.hydrate_by_ids.side_effect = lambda _c, batch: {i: _svc(i) for i in batch}

        from app.worker.backfill import backfill_services
        stats = await backfill_services(batch_size=2)

        assert stats["embedded"] == 5
        # 5 ids / batch 2 -> 3 batches -> 3 embed calls + 3 upserts
        assert embed.call_count == 3
        assert qdrant.bulk_upsert_points.call_count == 3

    async def test_skips_addons_and_nondefault_variations(self, mocks):
        mongo, qdrant, embed = mocks
        ids = ["a", "b", "c"]
        mongo.get_all_entity_ids.return_value = ids
        mongo.hydrate_by_ids.return_value = {
            "a": _svc("a"),
            "b": _svc("b", isAddOn=True),
            "c": _svc("c", variation={"variationGroupId": "g1"}, isDefaultVariationView=False),
        }

        from app.worker.backfill import backfill_services
        stats = await backfill_services(batch_size=100)

        assert stats["embedded"] == 1
        assert stats["skipped"] == 2

    async def test_batch_failure_counts_and_continues(self, mocks):
        mongo, qdrant, embed = mocks
        ids = ["a", "b", "c", "d"]
        mongo.get_all_entity_ids.return_value = ids
        mongo.hydrate_by_ids.side_effect = lambda _c, batch: {i: _svc(i) for i in batch}
        # First batch upsert fails, second succeeds.
        qdrant.bulk_upsert_points.side_effect = [Exception("qdrant down"), None]

        from app.worker.backfill import backfill_services
        stats = await backfill_services(batch_size=2)

        assert stats["failed"] == 2
        assert stats["embedded"] == 2
