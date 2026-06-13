"""Tests for TikTok services."""

from unittest.mock import MagicMock, patch
import pytest

from app.services.tiktok.downloader import download_video, get_video_info
from app.services.tiktok.playwright_provider import _parse_count, build_search_query


class TestTikTokUtils:
    """Test utility functions in TikTok playwright provider."""

    def test_parse_count_simple(self):
        assert _parse_count("123") == 123
        assert _parse_count(" 1,234 ") == 1234

    def test_parse_count_thousands(self):
        assert _parse_count("1.5K") == 1500
        assert _parse_count("500K") == 500000
        assert _parse_count("10.2k") == 10200

    def test_parse_count_millions(self):
        assert _parse_count("1.2M") == 1200000
        assert _parse_count("10m") == 10000000

    def test_parse_count_billions(self):
        assert _parse_count("1.5B") == 1500000000

    def test_parse_count_invalid(self):
        assert _parse_count("abc") == 0
        assert _parse_count("") == 0

    def test_build_search_query(self):
        assert build_search_query("Nike", "Air Max Shoes") == "Nike Air Max Shoes review"
        assert build_search_query(None, "Air Max Shoes") == "Air Max Shoes review"
        assert build_search_query("Nike", None) == "Nike review"
        # Checks that it limits the title to 5 words
        assert build_search_query("Brand", "One Two Three Four Five Six Seven") == "Brand One Two Three Four Five review"


class TestTikTokDownloader:
    """Test TikTok downloader with mocks."""

    def test_get_video_info(self):
        info = get_video_info("https://www.tiktok.com/@user/video/123456")
        assert info["title"] == ""
        assert info["creator"] == ""
        assert info["duration"] == 0

    @patch("app.services.tiktok.downloader.sync_playwright")
    @patch("app.services.tiktok.downloader._extract_video_info")
    @patch("app.services.tiktok.downloader._download_file")
    def test_download_video_success(self, mock_download_file, mock_extract_info, mock_playwright, tmp_path):
        from pathlib import Path
        # Mock Playwright context & page
        mock_pw = mock_playwright.return_value.start.return_value
        mock_context = mock_pw.chromium.launch_persistent_context.return_value
        mock_page = mock_context.new_page.return_value
        mock_context.cookies.return_value = [{"name": "tt", "value": "123", "domain": ".tiktok.com"}]
        mock_page.url = "https://www.tiktok.com/@user/video/123456"

        # Mock video extraction
        mock_extract_info.return_value = {
            "video_src": "https://example.com/video.mp4",
            "duration": 45,
        }

        # Mock downloading behavior (creates the file)
        def fake_download(url, path, cookies, referer, *args, **kwargs):
            Path(path).write_text("dummy mp4 content" * 100)

        mock_download_file.side_effect = fake_download

        with patch("app.services.tiktok.downloader.settings") as mock_settings:
            mock_settings.downloads_path = tmp_path
            res = download_video("https://www.tiktok.com/@user/video/123456", "B0CXYZ1234")
            
            assert "B0CXYZ1234_" in res["local_path"]
            assert res["duration_seconds"] == 45
            assert res["filesize_bytes"] > 0
            assert Path(res["local_path"]).exists()

    @patch("app.services.tiktok.downloader.sync_playwright")
    @patch("app.services.tiktok.downloader._extract_video_info")
    def test_download_video_too_long(self, mock_extract_info, mock_playwright, tmp_path):
        mock_pw = mock_playwright.return_value.start.return_value
        mock_context = mock_pw.chromium.launch_persistent_context.return_value
        
        mock_extract_info.return_value = {
            "video_src": "https://example.com/video.mp4",
            "duration": 1000,
        }

        with patch("app.services.tiktok.downloader.settings") as mock_settings:
            mock_settings.downloads_path = tmp_path
            with pytest.raises(ValueError, match="Video too long"):
                download_video("https://www.tiktok.com/@user/video/123456", "B0CXYZ1234", max_duration_seconds=900)

