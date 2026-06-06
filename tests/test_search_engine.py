import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.search_engine import normalize_query
from app.models.search import SearchRequest


class TestNormalizeQuery:
    def test_lowercases(self):
        assert normalize_query("Biryani") == "biryani"

    def test_collapses_whitespace(self):
        assert normalize_query("  paneer   tikka  ") == "paneer tikka"

    def test_does_not_alter_hinglish_tokens(self):
        result = normalize_query("paneer makhani")
        assert "paneer" in result
        assert "makhani" in result
