"""TikTok video downloader using yt-dlp."""

import logging
import time
from pathlib import Path

import yt_dlp

from app.config import settings

logger = logging.getLogger(__name__)

# yt-dlp options optimized for TikTok
YDL_OPTS_BASE = {
    "format": "best[ext=mp4]/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "socket_timeout": 30,
    "retries": 3,
    "noprogress": True,
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    },
}


def download_video(
    video_url: str,
    asin: str,
    max_duration_seconds: int = 900,  # 15 minutes
) -> dict:
    """
    Download a TikTok video to local filesystem.

    Args:
        video_url: Full TikTok video URL
        asin: Amazon ASIN (used in filename)
        max_duration_seconds: Reject videos longer than this

    Returns:
        dict with keys: local_path, duration_seconds, filesize_bytes

    Raises:
        ValueError: if video exceeds max duration or download fails
    """
    downloads_dir = settings.downloads_path
    timestamp = int(time.time())
    output_filename = f"{asin}_{timestamp}"
    output_template = str(downloads_dir / f"{output_filename}.%(ext)s")

    opts = {
        **YDL_OPTS_BASE,
        "outtmpl": output_template,
    }

    logger.info("Downloading TikTok video: %s", video_url)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # First, extract info to check duration
            info = ydl.extract_info(video_url, download=False)

            duration = info.get("duration", 0) or 0
            if duration > max_duration_seconds:
                raise ValueError(
                    f"Video too long: {duration}s (max {max_duration_seconds}s)"
                )

            # Now download
            info = ydl.extract_info(video_url, download=True)

            # Find the downloaded file
            downloaded_file = ydl.prepare_filename(info)
            local_path = Path(downloaded_file)

            if not local_path.exists():
                # Try with .mp4 extension
                local_path = local_path.with_suffix(".mp4")
                if not local_path.exists():
                    raise FileNotFoundError(
                        f"Downloaded file not found: {downloaded_file}"
                    )

            filesize = local_path.stat().st_size
            logger.info(
                "Downloaded: %s (%.1f MB, %ds)",
                local_path.name,
                filesize / 1024 / 1024,
                duration,
            )

            return {
                "local_path": str(local_path),
                "duration_seconds": int(duration),
                "filesize_bytes": filesize,
            }

    except yt_dlp.utils.DownloadError as e:
        logger.error("yt-dlp download failed: %s", e)
        raise ValueError(f"Video download failed: {e}") from e


def get_video_info(video_url: str) -> dict:
    """
    Extract video metadata without downloading.

    Returns:
        dict with keys: title, creator, duration, view_count, like_count
    """
    opts = {
        **YDL_OPTS_BASE,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)

    return {
        "title": info.get("title", ""),
        "creator": info.get("uploader", "") or info.get("creator", ""),
        "duration": info.get("duration", 0),
        "view_count": info.get("view_count", 0),
        "like_count": info.get("like_count", 0),
        "description": info.get("description", ""),
    }
