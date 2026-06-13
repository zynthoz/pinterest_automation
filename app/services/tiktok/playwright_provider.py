"""Playwright-based TikTok search provider.

Uses headless Chromium to search TikTok and scrape video results.
This is fragile by nature — TikTok's frontend changes frequently.
"""

import json
import logging
import random
import re
import time
from urllib.parse import quote_plus

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

    def search(self, query: str, max_results: int = 10, on_progress=None) -> list[TikTokResult]:
        """
        Search TikTok for videos matching the query.
        """
        def report_progress(msg: str):
            if on_progress:
                on_progress(msg)

        report_progress("Launching stealth browser...")
        context = self._ensure_context()
        page = context.new_page()

        # Mask webdriver detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        results: list[TikTokResult] = []

        try:
            # URL-encode the query to handle spaces and special characters
            encoded_query = quote_plus(query)
            search_url = f"https://www.tiktok.com/search/video?q={encoded_query}"
            logger.info("Searching TikTok: %s", search_url)
            report_progress(f"Searching TikTok for '{query}'...")
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)

            # Dismiss any cookie consent / CAPTCHA overlays
            self._dismiss_overlays(page)

            # Check for CAPTCHA and wait for manual solving if needed
            report_progress("Checking for CAPTCHA challenge...")
            self._handle_captcha(page, on_progress)

            # Wait for video content to render — TikTok is heavily JS-driven
            report_progress("Waiting for page layout to load...")
            time.sleep(random.uniform(4, 7))

            # Scroll to load more results
            report_progress("Scrolling search results page...")
            for _ in range(3):
                page.mouse.wheel(0, random.randint(800, 1500))
                time.sleep(random.uniform(2, 4))

            # Strategy 1: Extract from embedded JSON (most reliable when available)
            report_progress("Extracting TikTok video metadata...")
            results = self._extract_from_page(page, max_results)

            if not results:
                # Strategy 2: Scrape DOM elements directly
                results = self._extract_from_dom(page, max_results)

            if not results:
                # Strategy 3: Intercept API responses that may have loaded
                results = self._extract_from_network(page, max_results)

            logger.info("Found %d TikTok results for query: %s", len(results), query)
            report_progress(f"Found {len(results)} TikTok videos")

            # Debug: log page state if no results found
            if not results:
                try:
                    title = page.title()
                    url = page.url
                    body_text = page.inner_text("body")[:500]
                    logger.warning(
                        "No results found. Page title: %s | URL: %s | Body preview: %s",
                        title, url, body_text,
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.error("TikTok search failed: %s", e, exc_info=True)
            report_progress(f"TikTok search failed: {e}")
        finally:
            try:
                page.close()
            except Exception:
                pass

        # Sort by view count descending
        results.sort(key=lambda r: r.view_count, reverse=True)
        return results[:max_results]

    def _dismiss_overlays(self, page) -> None:
        """Try to dismiss cookie consent banners, CAPTCHAs, and login prompts."""
        overlay_selectors = [
            # Cookie consent
            'button[data-e2e="cookie-banner-accept"]',
            'button:has-text("Accept all")',
            'button:has-text("Accept cookies")',
            'button:has-text("Allow all")',
            # Login prompt dismiss
            'div[data-e2e="login-modal-close"] button',
            'button[data-e2e="modal-close-inner-button"]',
            'div[role="dialog"] button[aria-label="Close"]',
            # Generic close / dismiss buttons on overlays
            'div[class*="DivCloseIcon"]',
        ]

        for selector in overlay_selectors:
            try:
                el = page.locator(selector)
                if el.count() > 0 and el.first.is_visible():
                    el.first.click()
                    logger.debug("Dismissed overlay: %s", selector)
                    time.sleep(random.uniform(0.5, 1.0))
            except Exception:
                pass

    def _handle_captcha(self, page, on_progress=None) -> None:
        """Detect CAPTCHA challenges and wait for manual solving."""
        captcha_selectors = [
            # TikTok's various CAPTCHA containers
            'div[class*="captcha"]',
            'div[class*="Captcha"]',
            'div[id*="captcha"]',
            'iframe[src*="captcha"]',
            'div[class*="verify"]',
            'div[class*="Verify"]',
            'div[class*="secsdk-captcha"]',
            'div.cap_container',
            '#captcha-trigger',
            '.captcha_object',
        ]

        captcha_texts = [
            "drag the slider",
            "fit the puzzle",
            "select the items in the following order",
            "select matching",
            "verify to continue",
            "security check",
        ]

        has_captcha = False

        # Check main page selectors
        for selector in captcha_selectors:
            try:
                el = page.locator(selector)
                if el.count() > 0 and el.first.is_visible():
                    has_captcha = True
                    break
            except Exception:
                pass

        # Check main page texts
        if not has_captcha:
            for text in captcha_texts:
                try:
                    if page.get_by_text(text, exact=False).count() > 0:
                        has_captcha = True
                        break
                except Exception:
                    pass

        # Check all nested frames
        if not has_captcha:
            for frame in page.frames:
                try:
                    for selector in captcha_selectors:
                        el = frame.locator(selector)
                        if el.count() > 0 and el.first.is_visible():
                            has_captcha = True
                            break
                    if has_captcha:
                        break

                    for text in captcha_texts:
                        if frame.get_by_text(text, exact=False).count() > 0:
                            has_captcha = True
                            break
                    if has_captcha:
                        break
                except Exception:
                    pass

        if not has_captcha:
            return

        logger.warning(
            "CAPTCHA detected on TikTok! Please solve it manually in the browser window. "
            "Waiting up to 90 seconds..."
        )
        if on_progress:
            on_progress("CAPTCHA challenge detected! Please solve it in the Playwright window...")

        # Wait for the CAPTCHA to disappear (user solved it)
        start = time.time()
        timeout = 90

        while time.time() - start < timeout:
            captcha_visible = False

            # Check main page
            for selector in captcha_selectors:
                try:
                    el = page.locator(selector)
                    if el.count() > 0 and el.first.is_visible():
                        captcha_visible = True
                        break
                except Exception:
                    pass
            if not captcha_visible:
                for text in captcha_texts:
                    try:
                        if page.get_by_text(text, exact=False).count() > 0:
                            captcha_visible = True
                            break
                    except Exception:
                        pass

            # Check all frames
            if not captcha_visible:
                for frame in page.frames:
                    try:
                        for selector in captcha_selectors:
                            el = frame.locator(selector)
                            if el.count() > 0 and el.first.is_visible():
                                captcha_visible = True
                                break
                        if captcha_visible:
                            break

                        for text in captcha_texts:
                            if frame.get_by_text(text, exact=False).count() > 0:
                                captcha_visible = True
                                break
                        if captcha_visible:
                            break
                    except Exception:
                        pass

            if not captcha_visible:
                logger.info("CAPTCHA solved! Continuing...")
                if on_progress:
                    on_progress("CAPTCHA solved! Continuing...")
                time.sleep(random.uniform(1.0, 2.0))
                return

            time.sleep(2)

        logger.warning("CAPTCHA solving timed out after %ds. Continuing anyway...", timeout)
        if on_progress:
            on_progress("CAPTCHA solving timed out.")

    def _extract_from_page(self, page, max_results: int) -> list[TikTokResult]:
        """Try to extract video data from TikTok's embedded JSON state."""
        results = []

        try:
            # TikTok embeds data in script tags — try multiple known structures
            script_content = page.evaluate("""
                () => {
                    // Try SIGI_STATE (older structure)
                    const sigiEl = document.querySelector('#SIGI_STATE');
                    if (sigiEl) return sigiEl.textContent;

                    // Try __UNIVERSAL_DATA_FOR_REHYDRATION__ (newer structure)
                    const uniEl = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (uniEl) return uniEl.textContent;

                    // Try window.__INITIAL_STATE__
                    if (window.__INITIAL_STATE__) return JSON.stringify(window.__INITIAL_STATE__);

                    // Try to find any script tag containing video data
                    const scripts = document.querySelectorAll('script[type="application/json"]');
                    for (const s of scripts) {
                        const text = s.textContent || '';
                        if (text.includes('"video_id"') || text.includes('"ItemModule"') || text.includes('"videoData"')) {
                            return text;
                        }
                    }

                    return null;
                }
            """)

            if not script_content:
                logger.debug("No embedded JSON state found on TikTok page")
                return results

            data = json.loads(script_content)

            # Navigate the JSON structure to find video items
            items = {}

            # Structure 1: ItemModule (classic SIGI_STATE)
            if "ItemModule" in data:
                items = data["ItemModule"]

            # Structure 2: __UNIVERSAL_DATA_FOR_REHYDRATION__ → defaultScope
            elif "__DEFAULT_SCOPE__" in data:
                scope = data["__DEFAULT_SCOPE__"]
                # Look for search results in the scope
                for key, value in scope.items():
                    if isinstance(value, dict):
                        # Try to find item list in various sub-keys
                        if "data" in value and isinstance(value["data"], list):
                            for item in value["data"][:max_results]:
                                result = self._parse_universal_item(item)
                                if result:
                                    results.append(result)
                        elif "itemList" in value:
                            for item in value["itemList"][:max_results]:
                                result = self._parse_universal_item(item)
                                if result:
                                    results.append(result)

            # Structure 3: Search result format with nested data
            if not items and not results:
                # Walk the JSON tree looking for video-like objects
                items = self._find_video_items_recursive(data, max_depth=5)

            # Process ItemModule-style items
            for video_id, item in list(items.items())[:max_results]:
                try:
                    author = item.get("author", "")
                    if isinstance(author, dict):
                        author = author.get("uniqueId", author.get("nickname", ""))
                    stats = item.get("stats", {})
                    results.append(
                        TikTokResult(
                            video_url=f"https://www.tiktok.com/@{author}/video/{video_id}",
                            video_id=str(video_id),
                            creator_username=author,
                            creator_profile_url=f"https://www.tiktok.com/@{author}",
                            caption=item.get("desc", ""),
                            view_count=int(stats.get("playCount", stats.get("play_count", 0))),
                            like_count=int(stats.get("diggCount", stats.get("like_count", 0))),
                            comment_count=int(stats.get("commentCount", stats.get("comment_count", 0))),
                        )
                    )
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug("Skipping malformed item %s: %s", video_id, e)

        except (json.JSONDecodeError, Exception) as e:
            logger.debug("JSON extraction failed: %s", e)

        return results

    def _parse_universal_item(self, item: dict) -> TikTokResult | None:
        """Parse a video item from TikTok's universal data format."""
        try:
            # Handle nested author object
            author_data = item.get("author", {})
            if isinstance(author_data, str):
                author = author_data
            else:
                author = author_data.get("uniqueId", author_data.get("nickname", ""))

            video_id = str(item.get("id", item.get("video_id", "")))
            if not video_id or not author:
                return None

            stats = item.get("stats", item.get("statistics", {}))
            return TikTokResult(
                video_url=f"https://www.tiktok.com/@{author}/video/{video_id}",
                video_id=video_id,
                creator_username=author,
                creator_profile_url=f"https://www.tiktok.com/@{author}",
                caption=item.get("desc", item.get("description", "")),
                view_count=int(stats.get("playCount", stats.get("play_count", stats.get("viewCount", 0)))),
                like_count=int(stats.get("diggCount", stats.get("like_count", stats.get("likeCount", 0)))),
                comment_count=int(stats.get("commentCount", stats.get("comment_count", 0))),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def _find_video_items_recursive(self, data, max_depth: int = 5) -> dict:
        """Walk a nested dict/list looking for objects that look like TikTok video items."""
        items = {}
        if max_depth <= 0:
            return items

        if isinstance(data, dict):
            # Check if this dict itself looks like a video item
            if "video_id" in data or ("id" in data and "desc" in data and "author" in data):
                vid = str(data.get("video_id", data.get("id", "")))
                if vid:
                    items[vid] = data
            else:
                for value in data.values():
                    items.update(self._find_video_items_recursive(value, max_depth - 1))
        elif isinstance(data, list):
            for item in data:
                items.update(self._find_video_items_recursive(item, max_depth - 1))

        return items

    def _extract_from_dom(self, page, max_results: int) -> list[TikTokResult]:
        """Fallback: scrape video info directly from DOM elements."""
        results = []

        try:
            # Try multiple selector strategies for video cards
            video_links = []

            # Strategy 1: data-e2e search result items
            video_links = page.query_selector_all('div[data-e2e="search_top-item"] a')
            
            # Strategy 2: search-card items (newer layout)
            if not video_links:
                video_links = page.query_selector_all('div[data-e2e="search-card-item"] a')

            # Strategy 3: Any link containing /video/
            if not video_links:
                video_links = page.query_selector_all('a[href*="/video/"]')

            # Strategy 4: Video card containers
            if not video_links:
                video_links = page.query_selector_all(
                    'div[class*="DivItemCard"] a, '
                    'div[class*="ItemCard"] a, '
                    'div[class*="video-feed"] a[href*="video"]'
                )

            logger.debug("Found %d video link elements in DOM", len(video_links))

            seen_urls = set()
            for link in video_links[:max_results * 3]:
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
                    caption = ""
                    view_count = 0

                    try:
                        parent = link.evaluate_handle(
                            """el => {
                                // Walk up to find the card container
                                let p = el;
                                for (let i = 0; i < 8; i++) {
                                    p = p.parentElement;
                                    if (!p) break;
                                    if (p.className && (
                                        p.className.includes('Card') ||
                                        p.className.includes('item') ||
                                        p.className.includes('Item') ||
                                        p.dataset.e2e
                                    )) return p;
                                }
                                return el.parentElement?.parentElement || el.parentElement;
                            }"""
                        )

                        # Try to extract caption
                        for cap_sel in ['[class*="desc"]', '[class*="caption"]', '[class*="Desc"]', '[class*="Caption"]']:
                            try:
                                caption_el = parent.query_selector(cap_sel)
                                if caption_el:
                                    caption = caption_el.inner_text()
                                    if caption:
                                        break
                            except Exception:
                                pass

                        # Try to extract view count
                        for view_sel in ['[class*="view"]', '[class*="play"]', '[class*="View"]', '[class*="Play"]', 'strong']:
                            try:
                                views_el = parent.query_selector(view_sel)
                                if views_el:
                                    view_text = views_el.inner_text()
                                    parsed = _parse_count(view_text)
                                    if parsed > 0:
                                        view_count = parsed
                                        break
                            except Exception:
                                pass
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

    def _extract_from_network(self, page, max_results: int) -> list[TikTokResult]:
        """Strategy 3: Try to find video data from any XHR/fetch responses cached in the page."""
        results = []
        try:
            # Try to access TikTok's client-side data store
            data = page.evaluate("""
                () => {
                    try {
                        // Some TikTok pages store search results in window
                        const keys = Object.keys(window).filter(k =>
                            k.includes('SIGI') || k.includes('__NEXT') || k.includes('__APP')
                        );
                        for (const k of keys) {
                            const val = window[k];
                            if (val && typeof val === 'object') {
                                return JSON.stringify(val);
                            }
                        }
                    } catch(e) {}
                    return null;
                }
            """)

            if data:
                parsed = json.loads(data)
                items = self._find_video_items_recursive(parsed, max_depth=6)
                for video_id, item in list(items.items())[:max_results]:
                    result = self._parse_universal_item(item)
                    if result:
                        results.append(result)

        except Exception as e:
            logger.debug("Network extraction failed: %s", e)

        return results

    def close(self) -> None:
        """Shut down the browser."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
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
