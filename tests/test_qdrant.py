import uuid

import pytest

from app.db.qdrant import to_point_id
from app.core.reranker import rrf_fuse


class TestToPointId:
    def test_returns_valid_uuid_string(self):
        pid = to_point_id("663aaa000000000000000001")
        # Must be parseable as a UUID — Qdrant rejects raw 24-char hex ObjectIds.
        parsed = uuid.UUID(pid)
        assert str(parsed) == pid

    def test_is_deterministic(self):
        mongo_id = "663aaa000000000000000001"
        assert to_point_id(mongo_id) == to_point_id(mongo_id)

    def test_distinct_inputs_give_distinct_ids(self):
        assert to_point_id("663aaa000000000000000001") != to_point_id(
            "663aaa000000000000000002"
        )

    def test_raw_objectid_hex_is_not_used_directly(self):
        mongo_id = "663aaa000000000000000001"
        # The point id must NOT be the bare hex (which Qdrant rejects).
        assert to_point_id(mongo_id) != mongo_id


class TestRrfFuseKeysByMongoId:
    def _vector_hit(self, point_id, mongo_id, score):
        class Hit:
            pass

        h = Hit()
        h.id = point_id  # Qdrant point id (uuid5) — NOT the Mongo id
        h.score = score
        h.payload = {"entity_type": "service", "mongoId": mongo_id}
        return h

    def test_vector_hits_keyed_by_payload_mongo_id(self):
        # When a payload carries mongoId, fusion must key on it (not the uuid point id)
        # so vector and text hits for the same entity collapse and hydration works.
        mongo_id = "663aaa000000000000000002"
        vector_hits = [self._vector_hit(str(uuid.uuid4()), mongo_id, 0.9)]
        text_hits = [{"_id": mongo_id, "service": "test"}]
        scores = rrf_fuse(vector_hits, text_hits)
        assert mongo_id in scores
        # The two hits for the same entity must have fused into one bucket.
        assert len(scores) == 1
