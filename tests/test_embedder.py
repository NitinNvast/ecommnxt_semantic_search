import hashlib
import pytest
from app.core.embedder import (
    SEMANTIC_FIELDS,
    build_business_text,
    build_service_text,
    is_semantic_field_changed,
    source_hash,
)

SAMPLE_BUSINESS = {
    "businessName": "Spice Garden",
    "description": "Best <b>authentic</b> Indian food",
    "amenities": "AC seating",
    "secretKey": "DO_NOT_EMBED",
    "gstin": "27AAAAA0000A1Z5",
    "bankDetails": {"accountNumber": "123456"},
}

SAMPLE_RESOLVED_BUSINESS = {
    "category_name": "Restaurant",
    "subcategory_names": ["Indian", "Fast Food"],
    "brand_names": ["North Indian"],
}

SAMPLE_SERVICE = {
    "service": "Paneer Tikka",
    "description": "Grilled cottage cheese cubes",
    "productDetailDescription": [
        {"title": "Nutrients", "items": [{"label": "Protein", "value": "12g"}]}
    ],
}

SAMPLE_RESOLVED_SERVICE = {
    "category_name": "Starter",
    "brand_name": "",
    "country_name": "",
}


class TestBuildBusinessText:
    def test_includes_business_name(self):
        text = build_business_text(SAMPLE_BUSINESS, SAMPLE_RESOLVED_BUSINESS)
        assert "Spice Garden" in text

    def test_strips_html_from_description(self):
        text = build_business_text(SAMPLE_BUSINESS, SAMPLE_RESOLVED_BUSINESS)
        assert "<b>" not in text
        assert "authentic" in text

    def test_never_contains_pii_or_secrets(self):
        text = build_business_text(SAMPLE_BUSINESS, SAMPLE_RESOLVED_BUSINESS)
        assert "DO_NOT_EMBED" not in text
        assert "27AAAAA0000A1Z5" not in text
        assert "123456" not in text

    def test_includes_category_names(self):
        text = build_business_text(SAMPLE_BUSINESS, SAMPLE_RESOLVED_BUSINESS)
        assert "Restaurant" in text
        assert "North Indian" in text

    def test_empty_fields_are_skipped(self):
        sparse = {"businessName": "X"}
        text = build_business_text(sparse, {})
        assert "None" not in text
        assert "NA" not in text
        assert "null" not in text


class TestBuildServiceText:
    def test_includes_service_name(self):
        text = build_service_text(SAMPLE_SERVICE, SAMPLE_RESOLVED_SERVICE)
        assert "Paneer Tikka" in text

    def test_includes_product_detail_description(self):
        text = build_service_text(SAMPLE_SERVICE, SAMPLE_RESOLVED_SERVICE)
        assert "Protein" in text
        assert "12g" in text

    def test_never_contains_price(self):
        entity = {**SAMPLE_SERVICE, "cost": {"fixedCost": 250}}
        text = build_service_text(entity, SAMPLE_RESOLVED_SERVICE)
        assert "250" not in text


class TestSourceHash:
    def test_is_deterministic(self):
        text = "hello world"
        assert source_hash(text) == source_hash(text)

    def test_different_texts_produce_different_hashes(self):
        assert source_hash("abc") != source_hash("xyz")

    def test_matches_sha256(self):
        text = "paneer tikka"
        expected = hashlib.sha256(text.encode()).hexdigest()
        assert source_hash(text) == expected


class TestIsSemanticFieldChanged:
    def test_semantic_field_returns_true_for_business(self):
        assert is_semantic_field_changed("business", ["description"]) is True

    def test_volatile_field_returns_false_for_business(self):
        assert is_semantic_field_changed("business", ["overallRating"]) is False

    def test_semantic_field_returns_true_for_service(self):
        assert is_semantic_field_changed("service", ["brand"]) is True

    def test_volatile_field_returns_false_for_service(self):
        assert is_semantic_field_changed("service", ["cost"]) is False

    def test_mixed_fields_returns_true(self):
        assert is_semantic_field_changed("business", ["overallRating", "businessName"]) is True

    def test_empty_changed_fields_returns_false(self):
        assert is_semantic_field_changed("business", []) is False
