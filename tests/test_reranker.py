import pytest
from app.core.reranker import (
    haversine,
    proximity_decay,
    quality_boost,
    rrf_fuse,
)


class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine(18.52, 73.85, 18.52, 73.85) == pytest.approx(0.0)

    def test_known_distance(self):
        # Pune to Mumbai ≈ 120 km
        dist = haversine(18.52, 73.85, 19.07, 72.87)
        assert 110 < dist < 130


class TestProximityDecay:
    def test_zero_distance_gives_one(self):
        assert proximity_decay(0.0) == pytest.approx(1.0)

    def test_decay_is_less_than_one_for_positive_distance(self):
        assert proximity_decay(1.0) < 1.0

    def test_farther_distance_gives_lower_score(self):
        assert proximity_decay(5.0) < proximity_decay(1.0)

    def test_at_half_life_score_is_half(self):
        assert proximity_decay(2.0) == pytest.approx(0.5, rel=0.01)


class TestQualityBoost:
    def test_xirify_assured_boosts_score(self):
        assured = quality_boost({"xirifyAssured": True})
        plain = quality_boost({})
        assert assured > plain

    def test_top_rated_boosts_score(self):
        top = quality_boost({"topRated": True})
        plain = quality_boost({})
        assert top > plain

    def test_high_rating_boosts_score(self):
        high = quality_boost({"overallRating": 5.0})
        low = quality_boost({"overallRating": 1.0})
        assert high > low

    def test_score_is_capped_at_one(self):
        boosted = quality_boost({
            "xirifyAssured": True, "topRated": True, "popular": True,
            "isnew": True, "overallRating": 5.0,
        })
        assert boosted <= 1.0

    def test_empty_payload_returns_zero(self):
        assert quality_boost({}) == pytest.approx(0.0)


class TestRrfFuse:
    def _make_vector_hit(self, id_, score):
        class Hit:
            pass
        h = Hit()
        h.id = id_
        h.score = score
        h.payload = {"entity_type": "service"}
        return h

    def _make_text_hit(self, id_):
        return {"_id": id_, "service": "test"}

    def test_item_in_both_lists_has_higher_rrf_than_item_in_one(self):
        vector_hits = [
            self._make_vector_hit("aaa", 0.9),
            self._make_vector_hit("bbb", 0.7),
        ]
        text_hits = [
            self._make_text_hit("aaa"),
            self._make_text_hit("ccc"),
        ]
        scores = rrf_fuse(vector_hits, text_hits)
        assert scores["aaa"]["rrf_score"] > scores["bbb"]["rrf_score"]

    def test_item_not_in_vector_results_still_included(self):
        vector_hits = [self._make_vector_hit("aaa", 0.9)]
        text_hits = [self._make_text_hit("zzz")]
        scores = rrf_fuse(vector_hits, text_hits)
        assert "zzz" in scores

    def test_higher_rank_gives_higher_rrf(self):
        vector_hits = [
            self._make_vector_hit("first", 0.9),
            self._make_vector_hit("second", 0.8),
        ]
        scores = rrf_fuse(vector_hits, [])
        assert scores["first"]["rrf_score"] > scores["second"]["rrf_score"]
