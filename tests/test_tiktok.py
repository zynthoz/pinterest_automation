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

    @patch("app.services.tiktok.downloader.yt_dlp.YoutubeDL")
    def test_get_video_info(self, mock_ytdl):
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.return_value = {
            "title": "Test Title",
            "uploader": "test_creator",
            "duration": 60,
            "view_count": 1000,
            "like_count": 500,
            "description": "Test Desc",
        }

        info = get_video_info("https://www.tiktok.com/@user/video/123456")
        assert info["title"] == "Test Title"
        assert info["creator"] == "test_creator"
        assert info["duration"] == 60
        assert info["view_count"] == 1000

    @patch("app.services.tiktok.downloader.yt_dlp.YoutubeDL")
    def test_download_video_success(self, mock_ytdl, tmp_path):
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.side_effect = [
            {"duration": 45},  # First call: download=False
            {"title": "Test Title"},  # Second call: download=True
        ]
        
        # Mock prepare_filename to return a path inside tmp_path
        test_file = tmp_path / "B0CXYZ1234_123456.mp4"
        test_file.write_text("dummy mp4 content")
        instance.prepare_filename.return_value = str(test_file)

        with patch("app.services.tiktok.downloader.settings") as mock_settings:
            mock_settings.downloads_path = tmp_path
            res = download_video("https://www.tiktok.com/@user/video/123456", "B0CXYZ1234")
            
            assert res["local_path"] == str(test_file)
            assert res["duration_seconds"] == 45
            assert res["filesize_bytes"] > 0

    @patch("app.services.tiktok.downloader.yt_dlp.YoutubeDL")
    def test_download_video_too_long(self, mock_ytdl, tmp_path):
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.return_value = {"duration": 1000}

        with pytest.raises(ValueError, match="Video too long"):
            download_video("https://www.tiktok.com/@user/video/123456", "B0CXYZ1234", max_duration_seconds=900)
