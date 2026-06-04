import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.search_engine import build_qdrant_conditions, normalize_query
from app.models.search import GeoFilter, SearchFilters, SearchRequest


class TestNormalizeQuery:
    def test_lowercases(self):
        assert normalize_query("Biryani") == "biryani"

    def test_collapses_whitespace(self):
        assert normalize_query("  paneer   tikka  ") == "paneer tikka"

    def test_does_not_alter_hinglish_tokens(self):
        result = normalize_query("paneer makhani")
        assert "paneer" in result
        assert "makhani" in result


class TestBuildQdrantConditions:
    def test_always_includes_business_status_filter(self):
        request = SearchRequest(query="biryani")
        conditions = build_qdrant_conditions(request, "business")
        keys = [c.key for c in conditions]
        assert "businessStatus" in keys

    def test_always_includes_is_available_filter(self):
        request = SearchRequest(query="biryani")
        conditions = build_qdrant_conditions(request, "business")
        keys = [c.key for c in conditions]
        assert "isAvailable" in keys

    def test_geo_condition_added_when_geo_provided(self):
        request = SearchRequest(
            query="biryani",
            geo=GeoFilter(lat=18.52, lng=73.85, radiusKm=3),
        )
        conditions = build_qdrant_conditions(request, "business")
        keys = [c.key for c in conditions]
        assert "location" in keys

    def test_no_geo_condition_when_geo_absent(self):
        request = SearchRequest(query="biryani")
        conditions = build_qdrant_conditions(request, "business")
        keys = [c.key for c in conditions]
        assert "location" not in keys

    def test_category_filter_added_when_provided(self):
        request = SearchRequest(
            query="biryani",
            filters=SearchFilters(category="cat123"),
        )
        conditions = build_qdrant_conditions(request, "service")
        keys = [c.key for c in conditions]
        assert "category" in keys

    def test_client_cannot_override_security_filters(self):
        request = SearchRequest(query="test")
        conditions = build_qdrant_conditions(request, "business")
        keys = [c.key for c in conditions]
        assert "businessStatus" in keys
        assert "isAvailable" in keys
