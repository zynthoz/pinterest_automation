"""TikTok video downloader using Playwright.

Bypasses yt-dlp entirely — navigates to the TikTok video page in the
persistent Playwright browser, extracts the video source URL, and
downloads the file directly. This avoids issues with yt-dlp's TikTok
extractor breaking when TikTok changes their page structure.
"""

import json
import logging
import random
import re
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from app.config import settings

logger = logging.getLogger(__name__)

# Path to the persistent Playwright browser profile
PLAYWRIGHT_SESSION_DIR = Path.cwd() / "playwright_session"


def download_video(
    video_url: str,
    asin: str,
    max_duration_seconds: int = 900,  # 15 minutes
    on_progress=None,
) -> dict:
    """
    Download a TikTok video to local filesystem using Playwright.

    Opens the video page in the persistent browser session, extracts the
    direct video URL from the page, and downloads it.

    Args:
        video_url: Full TikTok video URL
        asin: Amazon ASIN (used in filename)
        max_duration_seconds: Reject videos longer than this
        on_progress: Optional callback function to receive progress updates

    Returns:
        dict with keys: local_path, duration_seconds, filesize_bytes

    Raises:
        ValueError: if video exceeds max duration or download fails
    """
    def report_progress(msg: str):
        if on_progress:
            on_progress(msg)

    downloads_dir = settings.downloads_path
    timestamp = int(time.time())
    output_filename = f"{asin}_{timestamp}.mp4"
    output_path = downloads_dir / output_filename

    logger.info("Downloading TikTok video via Playwright: %s", video_url)
    report_progress("Launching stealth browser for video download...")

    pw = sync_playwright().start()
    context = None
    page = None

    try:
        user_data_dir = str(PLAYWRIGHT_SESSION_DIR)
        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=settings.playwright_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )

        page = context.new_page()

        # Mask webdriver detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        # Intercept network responses from the start to catch video stream URLs
        intercepted_video_urls = []
        def handle_response(response):
            try:
                url = response.url
                content_type = response.headers.get("content-type", "")
                if "video" in content_type or "mime=video" in url or re.search(r"\.(mp4|webm)\b", url):
                    if url not in intercepted_video_urls:
                        intercepted_video_urls.append(url)
            except Exception:
                pass

        page.on("response", handle_response)

        # Navigate to the video page
        report_progress("Navigating to TikTok video page...")
        page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(random.uniform(3, 5))

        # Dismiss overlays (cookie consent, login prompts)
        report_progress("Checking for cookie consent / login overlays...")
        _dismiss_overlays(page)
        time.sleep(random.uniform(1, 2))

        # Extract video source URL and duration
        report_progress("Extracting direct video source URL...")
        video_info = _extract_video_info(page, intercepted_video_urls)

        if not video_info.get("video_src"):
            raise ValueError("Could not extract video source URL from TikTok page")

        video_src = video_info["video_src"]
        duration = video_info.get("duration", 0)

        if duration > max_duration_seconds:
            raise ValueError(
                f"Video too long: {duration}s (max {max_duration_seconds}s)"
            )

        logger.info("Found video source URL (%ds duration)", duration)

        # Download the video file using cookies from the browser session
        cookies = context.cookies()
        report_progress("Downloading video file...")
        _download_file(video_src, str(output_path), cookies, page.url, on_progress)

        if not output_path.exists():
            raise FileNotFoundError(f"Downloaded file not found: {output_path}")

        filesize = output_path.stat().st_size
        if filesize < 1000:
            # File too small — likely an error response, not a video
            output_path.unlink()
            raise ValueError(f"Downloaded file too small ({filesize} bytes), likely not a video")

        logger.info(
            "Downloaded: %s (%.1f MB, %ds)",
            output_path.name,
            filesize / 1024 / 1024,
            duration,
        )

        return {
            "local_path": str(output_path),
            "duration_seconds": int(duration),
            "filesize_bytes": filesize,
        }

    except Exception as e:
        logger.error("Playwright video download failed: %s", e, exc_info=True)
        report_progress(f"Download failed: {e}")
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Video download failed: {e}") from e
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        if context:
            try:
                context.close()
            except Exception:
                pass
        try:
            pw.stop()
        except Exception:
            pass


def _dismiss_overlays(page) -> None:
    """Dismiss cookie consent, login prompts, and other overlays."""
    selectors = [
        'button[data-e2e="cookie-banner-accept"]',
        'button:has-text("Accept all")',
        'button:has-text("Accept cookies")',
        'div[data-e2e="login-modal-close"] button',
        'button[data-e2e="modal-close-inner-button"]',
        'div[role="dialog"] button[aria-label="Close"]',
        'div[class*="DivCloseIcon"]',
    ]

    for selector in selectors:
        try:
            el = page.locator(selector)
            if el.count() > 0 and el.first.is_visible():
                el.first.click()
                time.sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass


def _extract_video_info(page, intercepted_video_urls: list) -> dict:
    """
    Extract the direct video URL and metadata from a TikTok video page.

    Tries multiple strategies since TikTok's page structure changes frequently.
    """
    info = {"video_src": None, "duration": 0}

    # Strategy 1: Check if we already intercepted the video stream URL from network responses
    if intercepted_video_urls:
        intercepted_video_urls.sort(key=len, reverse=True)
        info["video_src"] = intercepted_video_urls[0]
        info["duration"] = _get_video_duration(page)
        logger.info("Found video source from pre-intercepted network requests")
        return info

    # Strategy 2: Get video src directly from the <video> element
    info["video_src"] = _extract_from_video_element(page)
    if info["video_src"]:
        info["duration"] = _get_video_duration(page)
        return info

    # Strategy 3: Extract from embedded JSON data
    info["video_src"], info["duration"] = _extract_from_json(page)
    if info["video_src"]:
        return info

    # Strategy 4: Intercept network requests by force-playing the video
    info["video_src"] = _extract_by_playing(page, intercepted_video_urls)
    if info["video_src"]:
        info["duration"] = _get_video_duration(page)
        return info

    return info


def _extract_from_video_element(page) -> str | None:
    """Try to get the video URL from the <video> element's src or source tags."""
    try:
        video_src = page.evaluate("""
            () => {
                // Try <video> elements
                const videos = document.querySelectorAll('video');
                for (const v of videos) {
                    // Check src attribute
                    if (v.src && v.src.startsWith('http') && !v.src.includes('blob:')) {
                        return v.src;
                    }
                    // Check <source> children
                    const sources = v.querySelectorAll('source');
                    for (const s of sources) {
                        if (s.src && s.src.startsWith('http')) {
                            return s.src;
                        }
                    }
                    // Check currentSrc
                    if (v.currentSrc && v.currentSrc.startsWith('http') && !v.currentSrc.includes('blob:')) {
                        return v.currentSrc;
                    }
                }
                return null;
            }
        """)
        if video_src:
            logger.debug("Found video src from <video> element")
        return video_src
    except Exception as e:
        logger.debug("Video element extraction failed: %s", e)
        return None


def _extract_from_json(page) -> tuple[str | None, int]:
    """Extract video URL from TikTok's embedded JSON state."""
    try:
        json_data = page.evaluate("""
            () => {
                // Try __UNIVERSAL_DATA_FOR_REHYDRATION__
                const uniEl = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                if (uniEl) return uniEl.textContent;

                // Try SIGI_STATE
                const sigiEl = document.querySelector('#SIGI_STATE');
                if (sigiEl) return sigiEl.textContent;

                // Try __NEXT_DATA__
                const nextEl = document.querySelector('#__NEXT_DATA__');
                if (nextEl) return nextEl.textContent;

                // Try script tags with video data
                const scripts = document.querySelectorAll('script[type="application/json"]');
                for (const s of scripts) {
                    const text = s.textContent || '';
                    if (text.includes('playAddr') || text.includes('downloadAddr') || text.includes('video_url')) {
                        return text;
                    }
                }

                return null;
            }
        """)

        if not json_data:
            return None, 0

        data = json.loads(json_data)

        # Search recursively for video URLs in the JSON
        video_url, duration = _find_video_in_json(data)
        if video_url:
            logger.debug("Found video URL from embedded JSON")
        return video_url, duration

    except Exception as e:
        logger.debug("JSON extraction failed: %s", e)
        return None, 0


def _find_video_in_json(data, depth: int = 8) -> tuple[str | None, int]:
    """Recursively search JSON data for video download/play URLs."""
    if depth <= 0:
        return None, 0

    if isinstance(data, dict):
        # Check for known video URL keys
        for url_key in ["downloadAddr", "playAddr", "play_addr", "download_addr"]:
            val = data.get(url_key)
            if val:
                if isinstance(val, str) and val.startswith("http"):
                    duration = data.get("duration", 0)
                    if isinstance(duration, (int, float)):
                        duration = int(duration)
                    else:
                        duration = 0
                    return val, duration
                elif isinstance(val, dict):
                    uri = val.get("uri") or val.get("url_list", [None])[0] if val.get("url_list") else None
                    if uri and isinstance(uri, str):
                        return uri, int(data.get("duration", 0) or 0)
                elif isinstance(val, list) and val:
                    return str(val[0]), int(data.get("duration", 0) or 0)

        # Check for video object with nested URLs
        video_obj = data.get("video")
        if isinstance(video_obj, dict):
            result, dur = _find_video_in_json(video_obj, depth - 1)
            if result:
                return result, dur or int(data.get("duration", 0) or 0)

        # Check url_list pattern
        url_list = data.get("url_list")
        if isinstance(url_list, list) and url_list:
            for url in url_list:
                if isinstance(url, str) and "video" in url.lower():
                    return url, int(data.get("duration", 0) or 0)

        # Recurse into all values
        for value in data.values():
            result, dur = _find_video_in_json(value, depth - 1)
            if result:
                return result, dur

    elif isinstance(data, list):
        for item in data:
            result, dur = _find_video_in_json(item, depth - 1)
            if result:
                return result, dur

    return None, 0


def _extract_by_playing(page, intercepted_video_urls: list) -> str | None:
    """
    Click play on the video (using force to bypass overlay interception)
    and check if a video network request gets captured.
    """
    try:
        # Try to click the video to trigger playback
        video_el = page.locator("video")
        if video_el.count() > 0:
            logger.info("Attempting to click video to force play...")
            try:
                # Use force=True to bypass overlay pointer-events interception
                video_el.first.click(force=True)
            except Exception as ce:
                logger.debug("Force click failed: %s", ce)
            
            # Wait for playback/buffering to trigger a network response
            time.sleep(random.uniform(4, 6))

        if intercepted_video_urls:
            # Pick the longest URL (usually the actual video, not a preview)
            intercepted_video_urls.sort(key=len, reverse=True)
            logger.debug("Found video URL via network interception after clicking")
            return intercepted_video_urls[0]

    except Exception as e:
        logger.debug("Play-and-intercept failed: %s", e)

    return None


def _get_video_duration(page) -> int:
    """Try to get video duration from the page."""
    try:
        duration = page.evaluate("""
            () => {
                const video = document.querySelector('video');
                if (video && video.duration && isFinite(video.duration)) {
                    return Math.round(video.duration);
                }
                return 0;
            }
        """)
        return int(duration or 0)
    except Exception:
        return 0


def _download_file(url: str, output_path: str, cookies: list[dict], referer: str, on_progress=None) -> None:
    """Download a file from a URL using cookies from the browser session."""
    # Build cookie header string
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}" for c in cookies
        if "tiktok" in c.get("domain", "").lower()
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Origin": "https://www.tiktok.com",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str

    logger.info("Downloading video file...")
    bytes_downloaded = 0
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            total_bytes = int(resp.headers.get("Content-Length", 0))
            with open(output_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if on_progress:
                        if total_bytes > 0:
                            pct = int((bytes_downloaded / total_bytes) * 100)
                            on_progress(f"Downloading video: {pct}% ({bytes_downloaded // (1024*1024)}MB / {total_bytes // (1024*1024)}MB)")
                        else:
                            on_progress(f"Downloading video: {bytes_downloaded // (1024*1024)}MB downloaded")

    logger.info("Video file saved to: %s", output_path)


def get_video_info(video_url: str) -> dict:
    """
    Extract video metadata without downloading.

    Returns:
        dict with keys: title, creator, duration, view_count, like_count
    """
    # This is a lightweight version — just returns basic info
    # since we no longer use yt-dlp
    return {
        "title": "",
        "creator": "",
        "duration": 0,
        "view_count": 0,
        "like_count": 0,
        "description": "",
    }
