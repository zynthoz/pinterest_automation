"""Tests for AI copy generation service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.ai_copy import _validate_and_clean


class TestValidateAndClean:
    """Test AI output validation and cleanup."""

    def test_valid_output(self):
        data = {
            "title": "Amazing Product Review",
            "description": "Check out this product! Great for everyday use.",
            "hashtags": ["product", "review", "amazon"],
            "alt_text": "A product on a table",
        }
        result = _validate_and_clean(data, "testcreator")
        assert result["title"] == "Amazing Product Review"
        assert "product" in result["hashtags"]
        assert "testcreator" in result["description"]

    def test_title_truncation(self):
        data = {
            "title": "X" * 200,  # way too long
            "description": "Short desc.",
            "hashtags": ["a"],
            "alt_text": "alt",
        }
        result = _validate_and_clean(data, "creator")
        assert len(result["title"]) <= 100

    def test_ftc_disclosure_injected(self):
        data = {
            "title": "Product",
            "description": "Buy this product now!",
            "hashtags": [],
            "alt_text": "",
        }
        result = _validate_and_clean(data, "creator")
        assert "Amazon Associate" in result["description"]

    def test_creator_credit_injected(self):
        data = {
            "title": "Product",
            "description": "Great product description here.",
            "hashtags": [],
            "alt_text": "",
        }
        result = _validate_and_clean(data, "cool_creator")
        assert "@cool_creator" in result["description"]

    def test_hashtags_from_string(self):
        data = {
            "title": "Product",
            "description": "Desc",
            "hashtags": "tag1, tag2, #tag3",
            "alt_text": "",
        }
        result = _validate_and_clean(data, "c")
        assert "tag1" in result["hashtags"]
        assert "tag3" in result["hashtags"]
        assert "#" not in result["hashtags"]  # stripped

    def test_hashtags_with_hash_prefix(self):
        data = {
            "title": "Product",
            "description": "Desc",
            "hashtags": ["#amazon", "#review", "product"],
            "alt_text": "",
        }
        result = _validate_and_clean(data, "c")
        # Hash prefixes should be stripped
        assert "amazon" in result["hashtags"]
        assert "#amazon" not in result["hashtags"]

    def test_max_10_hashtags(self):
        data = {
            "title": "Product",
            "description": "Desc",
            "hashtags": [f"tag{i}" for i in range(20)],
            "alt_text": "",
        }
        result = _validate_and_clean(data, "c")
        tags = result["hashtags"].split(", ")
        assert len(tags) <= 10
