"""Playwright-based TikTok search provider.

Uses headless Chromium to search TikTok and scrape video results.
This is fragile by nature — TikTok's frontend changes frequently.
"""

import json
import logging
import random
import re
import time

from playwright.sync_api import Browser, Playwright, sync_playwright

from app.config import settings
from app.services.tiktok.base import TikTokProvider, TikTokResult

logger = logging.getLogger(__name__)

# Stealth viewport sizes to appear more natural
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]


class PlaywrightTikTokProvider(TikTokProvider):
    """TikTok search using Playwright browser automation."""

    def __init__(self):
        self._playwright: Playwright | None = None
        self._context = None

    def _ensure_context(self):
        """Lazily launch persistent browser context on first use."""
        from pathlib import Path
        if self._context is None:
            self._playwright = sync_playwright().start()
            viewport = random.choice(VIEWPORTS)
            user_data_dir = str(Path.cwd() / "playwright_session")
            
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=settings.playwright_headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                viewport=viewport,
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
            )
            logger.info("Launched persistent Playwright Chromium at %s", user_data_dir)
        return self._context

    def search(self, query: str, max_results: int = 10) -> list[TikTokResult]:
        """
        Search TikTok for videos matching the query.
        """
        context = self._ensure_context()
        page = context.new_page()

        # Mask webdriver detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        results: list[TikTokResult] = []

        try:
            search_url = f"https://www.tiktok.com/search/video?q={query}"
            logger.info("Searching TikTok: %s", search_url)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for video cards to appear
            time.sleep(random.uniform(3, 6))

            # Scroll to load more results
            for _ in range(3):
                page.mouse.wheel(0, random.randint(800, 1500))
                time.sleep(random.uniform(1.5, 3))

            # Try to extract video data from the page
            # TikTok renders data in SIGI_STATE or __UNIVERSAL_DATA_FOR_REHYDRATION__
            results = self._extract_from_page(page, max_results)

            if not results:
                # Fallback: try scraping DOM elements directly
                results = self._extract_from_dom(page, max_results)

            logger.info("Found %d TikTok results for query: %s", len(results), query)

        except Exception as e:
            logger.error("TikTok search failed: %s", e, exc_info=True)
        finally:
            context.close()

        # Sort by view count descending
        results.sort(key=lambda r: r.view_count, reverse=True)
        return results[:max_results]

    def _extract_from_page(self, page, max_results: int) -> list[TikTokResult]:
        """Try to extract video data from TikTok's embedded JSON state."""
        results = []

        try:
            # TikTok sometimes embeds data in a script tag
            script_content = page.evaluate("""
                () => {
                    // Try SIGI_STATE
                    const sigiEl = document.querySelector('#SIGI_STATE');
                    if (sigiEl) return sigiEl.textContent;

                    // Try __UNIVERSAL_DATA_FOR_REHYDRATION__
                    const uniEl = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (uniEl) return uniEl.textContent;

                    // Try window.__INITIAL_STATE__
                    if (window.__INITIAL_STATE__) return JSON.stringify(window.__INITIAL_STATE__);

                    return null;
                }
            """)

            if not script_content:
                return results

            data = json.loads(script_content)

            # Navigate the JSON structure to find video items
            # The structure varies but typically has ItemModule or similar
            items = {}
            if "ItemModule" in data:
                items = data["ItemModule"]
            elif "defaultScope" in data and "webapp.search" in str(data):
                # Newer TikTok structure
                pass

            for video_id, item in list(items.items())[:max_results]:
                try:
                    author = item.get("author", "")
                    stats = item.get("stats", {})
                    results.append(
                        TikTokResult(
                            video_url=f"https://www.tiktok.com/@{author}/video/{video_id}",
                            video_id=str(video_id),
                            creator_username=author,
                            creator_profile_url=f"https://www.tiktok.com/@{author}",
                            caption=item.get("desc", ""),
                            view_count=int(stats.get("playCount", 0)),
                            like_count=int(stats.get("diggCount", 0)),
                            comment_count=int(stats.get("commentCount", 0)),
                        )
                    )
                except (KeyError, ValueError) as e:
                    logger.debug("Skipping malformed item %s: %s", video_id, e)

        except (json.JSONDecodeError, Exception) as e:
            logger.debug("JSON extraction failed: %s", e)

        return results

    def _extract_from_dom(self, page, max_results: int) -> list[TikTokResult]:
        """Fallback: scrape video info directly from DOM elements."""
        results = []

        try:
            # Look for video card links
            video_links = page.query_selector_all('div[data-e2e="search_top-item"] a')
            if not video_links:
                video_links = page.query_selector_all('a[href*="/video/"]')

            seen_urls = set()
            for link in video_links[:max_results * 2]:
                try:
                    href = link.get_attribute("href") or ""
                    if "/video/" not in href or href in seen_urls:
                        continue
                    seen_urls.add(href)

                    # Extract video ID and creator from URL
                    match = re.search(r"@([^/]+)/video/(\d+)", href)
                    if not match:
                        continue

                    creator = match.group(1)
                    video_id = match.group(2)

                    # Try to get caption and view count from nearby elements
                    parent = link.evaluate_handle("el => el.closest('[class*=\"ItemCard\"]') || el.parentElement")
                    caption = ""
                    view_count = 0

                    try:
                        caption_el = parent.query_selector('[class*="desc"], [class*="caption"]')
                        if caption_el:
                            caption = caption_el.inner_text()
                    except Exception:
                        pass

                    try:
                        views_el = parent.query_selector('[class*="view"], [class*="play"]')
                        if views_el:
                            view_text = views_el.inner_text()
                            view_count = _parse_count(view_text)
                    except Exception:
                        pass

                    if not href.startswith("http"):
                        href = f"https://www.tiktok.com{href}"

                    results.append(
                        TikTokResult(
                            video_url=href,
                            video_id=video_id,
                            creator_username=creator,
                            creator_profile_url=f"https://www.tiktok.com/@{creator}",
                            caption=caption,
                            view_count=view_count,
                        )
                    )

                    if len(results) >= max_results:
                        break

                except Exception as e:
                    logger.debug("Error extracting video link: %s", e)

        except Exception as e:
            logger.debug("DOM extraction failed: %s", e)

        return results

    def close(self) -> None:
        """Shut down the browser."""
        if self._context:
            self._context.close()
            self._context = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None


def _parse_count(text: str) -> int:
    """Parse view/like counts like '1.2M', '500K', '1234'."""
    text = text.strip().upper().replace(",", "")
    try:
        if "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        elif "K" in text:
            return int(float(text.replace("K", "")) * 1_000)
        elif "B" in text:
            return int(float(text.replace("B", "")) * 1_000_000_000)
        else:
            return int(re.sub(r"[^\d]", "", text) or 0)
    except (ValueError, TypeError):
        return 0


def build_search_query(brand: str | None, title: str | None) -> str:
    """Build a TikTok search query from product info."""
    parts = []
    
    # Normalize inputs by removing punctuation
    brand_clean = re.sub(r'[^\w\s]', '', brand or '').strip()
    title_clean = re.sub(r'[^\w\s]', '', title or '').strip()
    
    if brand_clean:
        parts.append(brand_clean)
        
    if title_clean:
        # Take first ~5 meaningful words from title
        words = title_clean.split()[:5]
        # Avoid duplicating the brand if the title already starts with the brand name
        if brand_clean and words and words[0].lower() == brand_clean.lower():
            words = words[1:]
        parts.extend(words)
        
    parts.append("review")
    return " ".join([p for p in parts if p]).strip()
