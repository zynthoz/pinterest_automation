"""Tests for Amazon product extraction service."""

import pytest

from app.services.amazon import extract_asin, validate_affiliate_url


class TestExtractAsin:
    """Test ASIN extraction from various Amazon URL formats."""

    def test_standard_dp_url(self):
        url = "https://www.amazon.com/dp/B0CXYZ1234/"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_dp_url_with_title(self):
        url = "https://www.amazon.com/Some-Product-Name/dp/B0CXYZ1234/ref=sr_1_1"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_gp_product_url(self):
        url = "https://www.amazon.com/gp/product/B0CXYZ1234/"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_url_with_query_params(self):
        url = "https://www.amazon.com/dp/B0CXYZ1234?tag=mytag-20&linkCode=ll1"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_amazon_uk_url(self):
        url = "https://www.amazon.co.uk/dp/B0CXYZ1234/"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_amazon_de_url(self):
        url = "https://www.amazon.de/dp/B0CXYZ1234/"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_mobile_url(self):
        url = "https://www.amazon.com/gp/aw/d/B0CXYZ1234/"
        assert extract_asin(url) == "B0CXYZ1234"

    def test_invalid_url(self):
        assert extract_asin("https://www.google.com") is None

    def test_no_asin_in_url(self):
        assert extract_asin("https://www.amazon.com/deals") is None

    def test_empty_string(self):
        assert extract_asin("") is None

    def test_url_with_spaces(self):
        url = "  https://www.amazon.com/dp/B0CXYZ1234/  "
        assert extract_asin(url) == "B0CXYZ1234"


class TestValidateAffiliateUrl:
    """Test affiliate URL validation."""

    def test_valid_amazon_com(self):
        assert validate_affiliate_url("https://www.amazon.com/dp/B0CXYZ1234/")

    def test_valid_amazon_uk(self):
        assert validate_affiliate_url("https://www.amazon.co.uk/dp/B0CXYZ1234/")

    def test_valid_short_link(self):
        assert validate_affiliate_url("https://amzn.to/abc123")

    def test_valid_a_co(self):
        assert validate_affiliate_url("https://a.co/d/abc123")

    def test_invalid_google(self):
        assert not validate_affiliate_url("https://www.google.com")

    def test_invalid_ebay(self):
        assert not validate_affiliate_url("https://www.ebay.com/itm/123")

    def test_empty(self):
        assert not validate_affiliate_url("")
