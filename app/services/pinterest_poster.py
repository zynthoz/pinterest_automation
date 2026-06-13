"""Playwright-based Pinterest pin poster.

Automates pin creation through Pinterest's web UI instead of the API,
so no API approval is needed. Uses a persistent browser context to
preserve login sessions between runs.

Usage:
    poster = PinterestPoster()
    result = poster.create_pin(
        media_path="/path/to/video.mp4",
        title="My Pin Title",
        description="Pin description with hashtags",
        link="https://example.com/product",
        board_name="My Board",
    )
    poster.close()
"""

import logging
import random
import time
from pathlib import Path

from playwright.sync_api import (
    Playwright,
    sync_playwright,
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

from app.config import settings

logger = logging.getLogger(__name__)

# Viewport sizes to rotate through for fingerprint variation
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]

PIN_CREATION_URL = "https://www.pinterest.com/pin-creation-tool/"
PINTEREST_HOME = "https://www.pinterest.com/"


class PinterestPostError(Exception):
    """Raised when Playwright-based pin posting fails."""

    def __init__(self, message: str, step: str = "unknown"):
        self.step = step
        super().__init__(f"Pinterest post failed at '{step}': {message}")


class PinterestPoster:
    """Publish pins to Pinterest via browser automation (Playwright).

    Uses a persistent Chromium context stored in ./playwright_session/
    so you only need to log in once manually.
    """

    def __init__(self):
        self._playwright: Playwright | None = None
        self._context = None

    # ─── Browser Lifecycle ──────────────────────────────────────

    def _ensure_context(self):
        """Lazily launch a persistent headed Chromium context."""
        if self._context is not None:
            return self._context

        self._playwright = sync_playwright().start()
        viewport = random.choice(VIEWPORTS)
        user_data_dir = str(Path.cwd() / "playwright_session")

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,  # Always headed for Pinterest posting
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
        logger.info("Launched persistent Playwright Chromium (headed) at %s", user_data_dir)
        return self._context

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

    # ─── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _random_delay(min_s: float = 1.0, max_s: float = 3.0) -> None:
        """Sleep for a randomized duration to mimic human pacing."""
        delay = random.uniform(min_s, max_s)
        logger.debug("Waiting %.1fs...", delay)
        time.sleep(delay)

    @staticmethod
    def _human_type(page, selector: str, text: str) -> None:
        """Type text character-by-character with random inter-key delays."""
        element = page.locator(selector)
        element.click()
        time.sleep(random.uniform(0.3, 0.6))
        for char in text:
            page.keyboard.type(char, delay=random.randint(30, 120))
        time.sleep(random.uniform(0.2, 0.5))

    # ─── Login Check ────────────────────────────────────────────

    def _ensure_logged_in(self, page, on_progress=None) -> None:
        """Verify the user is logged in, or pause for manual login."""
        logger.info("Checking Pinterest login status...")
        if on_progress:
            on_progress("Checking Pinterest login status...")
        page.goto(PINTEREST_HOME, wait_until="domcontentloaded", timeout=30000)
        self._random_delay(2.0, 4.0)

        # If we land on a login page or see a login button, we're not logged in
        login_indicators = [
            'div[data-test-id="loginButton"]',
            'button[data-test-id="simple-login-button"]',
            'a[href="/login/"]',
        ]

        is_logged_in = True
        for selector in login_indicators:
            if page.locator(selector).count() > 0:
                is_logged_in = False
                break

        if not is_logged_in:
            logger.warning(
                "Not logged in to Pinterest! Please log in manually in the browser window. "
                "Waiting up to 120 seconds..."
            )
            if on_progress:
                on_progress("Not logged in! Please log in manually in the browser window (waiting up to 120s)...")
            # Wait for the user to complete login — look for the home feed
            try:
                page.wait_for_selector(
                    'div[data-test-id="homefeed"], div[data-test-id="header-avatar"]',
                    timeout=120000,
                )
                logger.info("Login detected! Continuing...")
                if on_progress:
                    on_progress("Login detected! Continuing...")
                self._random_delay(2.0, 3.0)
            except PlaywrightTimeout:
                raise PinterestPostError(
                    "Timed out waiting for manual login (120s). "
                    "Please log in and try again.",
                    step="login",
                )
        else:
            logger.info("Already logged in to Pinterest.")
            if on_progress:
                on_progress("Already logged in to Pinterest.")

    # ─── Main Pin Creation ──────────────────────────────────────

    def create_pin(
        self,
        media_path: str,
        title: str,
        description: str,
        link: str,
        board_name: str,
        on_progress=None,
    ) -> dict:
        """
        Create and publish a pin via Pinterest's web UI.

        Args:
            media_path: Local path to the image or video file to upload.
            title: Pin title (max 100 chars on Pinterest).
            description: Pin description text.
            link: Destination URL for the pin.
            board_name: Display name of the target Pinterest board.
            on_progress: Optional callback function to receive progress updates.

        Returns:
            dict with keys: success (bool), message (str), pin_url (str|None)

        Raises:
            PinterestPostError: If any step of the posting process fails.
        """
        def report_progress(msg: str):
            if on_progress:
                on_progress(msg)

        media_file = Path(media_path)
        if not media_file.exists():
            raise PinterestPostError(f"Media file not found: {media_path}", step="validation")

        report_progress("Launching headed browser for Pinterest...")
        context = self._ensure_context()
        page = context.new_page()

        # Mask webdriver detection
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        try:
            # Step 0: Ensure we're logged in
            self._ensure_logged_in(page, on_progress)

            # Step 1: Navigate to pin creation tool
            logger.info("Navigating to pin creation tool...")
            report_progress("Navigating to Pinterest pin-creation tool...")
            page.goto(PIN_CREATION_URL, wait_until="domcontentloaded", timeout=30000)
            self._random_delay(2.0, 4.0)

            # Step 2: Upload media file
            report_progress("Uploading media file to Pinterest...")
            self._upload_media(page, str(media_file.resolve()), on_progress)

            # Step 3: Fill in pin details
            report_progress("Filling in pin title...")
            self._fill_title(page, title[:100])
            report_progress("Filling in pin description...")
            self._fill_description(page, description[:500])
            report_progress("Filling in destination link...")
            self._fill_link(page, link)

            # Step 4: Select board
            report_progress(f"Selecting board '{board_name}'...")
            self._select_board(page, board_name)

            # Step 5: Publish
            report_progress("Publishing pin...")
            result = self._publish(page, on_progress)

            logger.info("Pin published successfully!")
            report_progress("Pin published successfully!")
            return result

        except PinterestPostError:
            raise
        except PlaywrightTimeout as exc:
            raise PinterestPostError(str(exc), step="timeout") from exc
        except Exception as exc:
            raise PinterestPostError(str(exc), step="unexpected") from exc
        finally:
            try:
                page.close()
            except Exception:
                pass

    # ─── Step Implementations ───────────────────────────────────

    def _upload_media(self, page, file_path: str, on_progress=None) -> None:
        """Upload an image or video file to the pin creation form."""
        logger.info("Uploading media: %s", file_path)
        if on_progress:
            on_progress("Attaching media file...")

        # Pinterest's upload area uses a hidden file input
        # Look for common file input selectors
        file_input_selectors = [
            'input[type="file"][accept*="image"]',
            'input[type="file"][accept*="video"]',
            'input[type="file"]',
        ]

        file_input = None
        for selector in file_input_selectors:
            inputs = page.locator(selector)
            if inputs.count() > 0:
                file_input = inputs.first
                break

        if file_input is None:
            raise PinterestPostError(
                "Could not find file upload input on pin creation page",
                step="upload",
            )

        file_input.set_input_files(file_path)
        logger.info("Media file attached. Waiting for upload to process...")
        if on_progress:
            on_progress("Waiting for media upload to process...")
        self._random_delay(3.0, 6.0)

        # Wait for upload to complete — look for the media preview or progress indicators to clear
        try:
            # Wait for any upload progress indicator to disappear
            page.wait_for_selector(
                'div[data-test-id="pin-draft-media-preview"], '
                'div[data-test-id="storyboard-preview"], '
                'video, img[data-test-id="pin-closeup-image"]',
                timeout=60000,
            )
            logger.info("Media upload complete.")
            if on_progress:
                on_progress("Media upload complete.")
        except PlaywrightTimeout:
            # Media might still be processing — continue anyway
            logger.warning("Media preview not detected, but continuing...")

        self._random_delay(1.5, 3.0)

    def _fill_title(self, page, title: str) -> None:
        """Fill in the pin title field."""
        logger.info("Filling title: %s", title[:50])

        title_selectors = [
            'input[id="pin-draft-title"]',
            'input[placeholder*="title" i]',
            'input[data-test-id="pin-draft-title"]',
            'textarea[data-test-id="pin-draft-title"]',
            '[data-test-id="storyboard-title-field-container"] textarea',
            '[data-test-id="storyboard-title-field-container"] input',
            '[data-test-id="storyboard-title-field-container"] [contenteditable="true"]',
            '[data-test-id="storyboard-title-field-container"] div[role="textbox"]',
            '[data-test-id="storyboard-title-field-container"] div',
            '[data-test-id="storyboard-title-field-container"] span',
            '[data-test-id="storyboard-title-field-container"]',
        ]

        for selector in title_selectors:
            try:
                if page.locator(selector).count() > 0:
                    self._human_type(page, selector, title)
                    self._random_delay(0.8, 1.5)
                    return
            except Exception as e:
                logger.warning("Failed typing in title selector %s: %s", selector, e)

        # Fallback: try aria labels
        try:
            title_field = page.get_by_placeholder("Add a title")
            if title_field.count() > 0:
                title_field.click()
                self._random_delay(0.3, 0.6)
                title_field.fill(title)
                self._random_delay(0.8, 1.5)
                return
        except Exception:
            pass

        raise PinterestPostError("Could not find title input field", step="title")

    def _fill_description(self, page, description: str) -> None:
        """Fill in the pin description field."""
        logger.info("Filling description (%d chars)...", len(description))

        desc_selectors = [
            'textarea[id="pin-draft-description"]',
            'div[data-test-id="pin-draft-description"] textarea',
            'textarea[placeholder*="description" i]',
            'textarea[data-test-id="pin-draft-description"]',
            '[data-test-id="storyboard-description-field-container"] textarea',
            '[data-test-id="storyboard-description-field-container"] [contenteditable="true"]',
            '[data-test-id="storyboard-description-field-container"] div[role="textbox"]',
            '[data-test-id="storyboard-description-field-container"] p',
            '[data-test-id="storyboard-description-field-container"] div',
            '[data-test-id="storyboard-description-field-container"] span',
            '[data-test-id="storyboard-description-field-container"]',
        ]

        for selector in desc_selectors:
            try:
                if page.locator(selector).count() > 0:
                    self._human_type(page, selector, description)
                    self._random_delay(0.8, 1.5)
                    return
            except Exception as e:
                logger.warning("Failed typing in description selector %s: %s", selector, e)

        # Fallback: placeholder text
        try:
            desc_field = page.get_by_placeholder("Tell everyone what your Pin is about")
            if desc_field.count() > 0:
                desc_field.click()
                self._random_delay(0.3, 0.6)
                desc_field.fill(description)
                self._random_delay(0.8, 1.5)
                return
        except Exception:
            pass

        raise PinterestPostError("Could not find description input field", step="description")

    def _fill_link(self, page, link: str) -> None:
        """Fill in the destination link field."""
        logger.info("Filling destination link: %s", link[:60])

        link_selectors = [
            'input[id="pin-draft-link"]',
            'input[placeholder*="link" i]',
            'input[data-test-id="pin-draft-link"]',
            'input[placeholder*="url" i]',
            'input[placeholder*="destination" i]',
            '[data-test-id="storyboard-link-field-container"] input',
            '[data-test-id="storyboard-link-field-container"] [contenteditable="true"]',
            '[data-test-id="storyboard-link-field-container"] div[role="textbox"]',
            '[data-test-id="storyboard-link-field-container"] div',
            '[data-test-id="storyboard-link-field-container"] span',
            '[data-test-id="storyboard-link-field-container"]',
        ]

        for selector in link_selectors:
            try:
                if page.locator(selector).count() > 0:
                    self._human_type(page, selector, link)
                    self._random_delay(0.8, 1.5)
                    return
            except Exception as e:
                logger.warning("Failed typing in link selector %s: %s", selector, e)

        # Fallback: placeholder
        try:
            link_field = page.get_by_placeholder("Add a destination link")
            if link_field.count() > 0:
                link_field.click()
                self._random_delay(0.3, 0.6)
                link_field.fill(link)
                self._random_delay(0.8, 1.5)
                return
        except Exception:
            pass

        raise PinterestPostError("Could not find link input field", step="link")

    def _select_board(self, page, board_name: str) -> None:
        """Select the target board from the board picker dropdown."""
        logger.info("Selecting board: %s", board_name)

        # Click the board selector button/dropdown
        board_selector_triggers = [
            '[data-test-id="board-dropdown-select-button"]',
            '[data-test-id="boardDropdownSelectButton"]',
            '[data-test-id="storyboard-selector-board"]',
            '[data-test-id="board-dropdown-placeholder"]',
            'div[data-test-id="board-dropdown"] button',
            'button[aria-label*="board" i]',
            'div[data-test-id="pin-draft-board-selector"]',
        ]

        clicked = False
        for selector in board_selector_triggers:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    # Wait up to 5 seconds for the element to be visible
                    loc.first.wait_for(state="visible", timeout=5000)
                    
                    # Wait for aria-disabled="true" to go away if it is disabled
                    start_wait = time.time()
                    while time.time() - start_wait < 15:
                        aria_disabled = loc.first.get_attribute("aria-disabled")
                        if aria_disabled != "true":
                            break
                        logger.info("Board dropdown trigger is disabled. Waiting for upload/processing...")
                        self._random_delay(0.5, 1.0)
                        
                    loc.first.click()
                    clicked = True
                    break
            except Exception as e:
                logger.warning("Failed trying to click board trigger selector %s: %s", selector, e)

        if not clicked:
            # Try broader search for the board dropdown
            try:
                board_buttons = page.locator(
                    'button:has-text("Select a board"), '
                    'button:has-text("Choose board"), '
                    '[role="button"]:has-text("Choose a board"), '
                    '[role="button"]:has-text("Select a board")'
                )
                if board_buttons.count() > 0:
                    board_buttons.first.click()
                    clicked = True
            except Exception as e:
                logger.warning("Failed trying broad button search: %s", e)

        if not clicked:
            raise PinterestPostError(
                "Could not find board selector dropdown",
                step="board_select",
            )

        self._random_delay(1.0, 2.0)

        # Search for the board if there's a search input in the dropdown
        board_search = page.locator(
            'input[data-test-id="board-dropdown-search"], '
            'input[placeholder*="Search" i], '
            'input[placeholder*="board" i], '
            '[role="searchbox"] input, '
            '[role="dialog"] input'
        )
        if board_search.count() > 0:
            try:
                board_search.first.click()
                self._random_delay(0.3, 0.6)
                board_search.first.fill(board_name)
                self._random_delay(1.0, 2.0)
            except Exception as e:
                logger.warning("Failed typing in board search: %s", e)

        # Click the matching board option
        # Try multiple selectors for the board list items
        board_option = page.locator(
            f'div[data-test-id="board-row"]:has-text("{board_name}"), '
            f'[data-test-id*="board-row"]:has-text("{board_name}"), '
            f'li:has-text("{board_name}"), '
            f'div[role="option"]:has-text("{board_name}"), '
            f'div[role="menuitem"]:has-text("{board_name}")'
        )

        clicked_option = False
        if board_option.count() > 0:
            try:
                board_option.first.click()
                clicked_option = True
                logger.info("Board '%s' selected.", board_name)
            except Exception as e:
                logger.warning("Failed clicking board option: %s", e)

        if not clicked_option:
            # Fallback 1: click by exact text match
            try:
                exact_match = page.get_by_text(board_name, exact=True)
                if exact_match.count() > 0:
                    exact_match.first.click()
                    clicked_option = True
                    logger.info("Board '%s' selected (exact text match).", board_name)
            except Exception:
                pass

        if not clicked_option:
            # Fallback 2: click by contains text match
            try:
                contains_match = page.get_by_text(board_name, exact=False)
                if contains_match.count() > 0:
                    contains_match.first.click()
                    clicked_option = True
                    logger.info("Board '%s' selected (contains text match).", board_name)
            except Exception:
                pass

        if not clicked_option:
            raise PinterestPostError(
                f"Board '{board_name}' not found in dropdown. "
                "Make sure the board name matches exactly.",
                step="board_select",
            )

        self._random_delay(1.0, 2.0)

    def _publish(self, page, on_progress=None) -> dict:
        """Click the Publish button and wait for confirmation."""
        logger.info("Publishing pin...")

        publish_selectors = [
            '[data-test-id="board-dropdown-save-button"]',
            '[data-test-id="create-new-pin-button"]',
            '[data-test-id="pin-draft-publish-button"] button',
            '[data-test-id="pin-draft-publish-button"]',
            '[data-test-id*="publish"] button',
            '[data-test-id*="publish"]',
            'button:has-text("Publish")',
            'button:has-text("Save")',
            '[role="button"]:has-text("Publish")',
            '[role="button"]:has-text("Save")',
        ]

        clicked = False
        for selector in publish_selectors:
            loc = page.locator(selector)
            if loc.count() > 0:
                # Make sure it's visible and enabled
                try:
                    loc.first.wait_for(state="visible", timeout=5000)
                    loc.first.click()
                    clicked = True
                    break
                except Exception as e:
                    logger.warning("Failed trying to click publish selector %s: %s", selector, e)
                    continue

        if not clicked:
            raise PinterestPostError(
                "Could not find or click the Publish button",
                step="publish",
            )

        self._random_delay(3.0, 5.0)

        # Wait for success confirmation or navigation
        # Pinterest typically shows a success toast or redirects
        result = {"success": False, "message": "", "pin_url": None}

        if on_progress:
            on_progress("Waiting for publish confirmation from Pinterest...")

        _SUCCESS_URL_HINTS = (
            "/business/hub",
            "/pin/",
            "/success",
            "/created",
        )

        start_time = time.time()
        selector_str = (
            'a:has-text("See it now"), '
            'div[data-test-id="toast"]:has-text("created"), '
            'div:has-text("Your Pin has been"), '
            'a[href*="/pin/"]'
        )

        while time.time() - start_time < 30.0:
            try:
                # 1. Check current URL first (fast path for redirects)
                current_url = page.url
                if any(hint in current_url for hint in _SUCCESS_URL_HINTS):
                    logger.info("Success inferred from current page URL: %s", current_url)
                    result["success"] = True
                    result["message"] = "Pin published successfully (confirmed via redirect)"
                    if "/pin/" in current_url:
                        result["pin_url"] = current_url
                    return result

                # 2. Wait for selector with a very short timeout
                page.wait_for_selector(selector_str, timeout=2000)
                result["success"] = True
                result["message"] = "Pin published successfully"

                # Try to extract the pin URL from "See it now" link
                see_it = page.locator('a:has-text("See it now"), a[href*="/pin/"]')
                if see_it.count() > 0:
                    pin_url = see_it.first.get_attribute("href")
                    if pin_url and "/pin/" in pin_url:
                        if not pin_url.startswith("http"):
                            pin_url = f"https://www.pinterest.com{pin_url}"
                        result["pin_url"] = pin_url
                        logger.info("Pin URL: %s", pin_url)
                return result

            except PlaywrightTimeout:
                # Continue loop until 30s elapsed
                continue
            except PlaywrightError as exc:
                # Browser/page context closed - check if navigation/call log implies success
                check_text = ""
                try:
                    check_text += page.url
                except Exception:
                    pass
                check_text += " " + str(exc)

                if any(hint in check_text.lower() for hint in _SUCCESS_URL_HINTS):
                    logger.info("Success inferred from Playwright error/call log: %s", check_text)
                    result["success"] = True
                    result["message"] = "Pin published successfully (confirmed via hub redirect)"
                    # See if we can grab a pin URL from the error trace / url
                    for word in check_text.split():
                        if "/pin/" in word:
                            # clean up brackets/quotes
                            clean_word = word.strip('"\'(),')
                            if not clean_word.startswith("http"):
                                clean_word = f"https://www.pinterest.com{clean_word}"
                            result["pin_url"] = clean_word
                    return result

                # Real unexpected error (no success indicator found), re-raise
                raise PinterestPostError(
                    f"Pinterest post failed at 'unexpected': {exc}",
                    step="unexpected",
                ) from exc

        # If we reach here, 30 seconds have elapsed without finding a success indicator
        # Double check if we navigated away from the creation page
        try:
            current_url = page.url
            if PIN_CREATION_URL not in current_url:
                result["success"] = True
                result["message"] = f"Pin likely published (page navigated to {current_url})"
                return result

            # Check for error elements on page
            for err_text in ["already pinned", "something went wrong", "invalid link", "try again"]:
                if page.get_by_text(err_text, exact=False).count() > 0:
                    raise PinterestPostError(f"Pinterest showed error: {err_text}", step="publish_confirm")
        except PinterestPostError:
            raise
        except Exception:
            pass

        raise PinterestPostError(
            "Timed out waiting for publish confirmation. The creation page remains open without confirmation.",
            step="publish_confirm",
        )
