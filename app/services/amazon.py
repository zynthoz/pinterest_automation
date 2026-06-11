"""Amazon product extraction — ASIN parsing and product page scraping."""

import logging
import random
import re
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common ASIN patterns in Amazon URLs
ASIN_PATTERNS = [
    re.compile(r"/dp/([A-Z0-9]{10})"),
    re.compile(r"/gp/product/([A-Z0-9]{10})"),
    re.compile(r"/gp/aw/d/([A-Z0-9]{10})"),
    re.compile(r"/exec/obidos/asin/([A-Z0-9]{10})"),
    re.compile(r"(?:amazon\.[a-z.]+/.*?)([A-Z0-9]{10})(?:/|$|\?)"),
]

# Rotate user agents to reduce blocking
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


@dataclass
class ProductInfo:
    """Scraped product data from Amazon."""

    asin: str
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    image_url: str | None = None
    price: str | None = None


def extract_asin(url: str) -> str | None:
    """
    Extract the Amazon ASIN from various URL formats.

    Supports:
        - /dp/B0XXXXXXXX/
        - /gp/product/B0XXXXXXXX/
        - Short links (amzn.to/xxx) — follows redirect
    """
    url = url.strip()

    # Handle Amazon short links by following redirect
    if "amzn.to/" in url or "a.co/" in url:
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                resp = client.head(url)
                url = str(resp.url)
        except httpx.HTTPError:
            logger.warning("Failed to resolve short URL: %s", url)
            return None

    # Try each ASIN pattern
    for pattern in ASIN_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)

    logger.warning("Could not extract ASIN from URL: %s", url)
    return None


def _get_headers() -> dict[str, str]:
    """Generate randomized browser headers."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def scrape_product(asin: str, retries: int = 3) -> ProductInfo:
    """
    Scrape product info from Amazon product page.

    Uses BeautifulSoup to parse title, brand, category, image, and price.
    Retries with exponential backoff on failure.
    """
    url = f"https://www.amazon.com/dp/{asin}"
    info = ProductInfo(asin=asin)

    for attempt in range(retries):
        try:
            # Random delay to appear more human-like
            time.sleep(random.uniform(2, 5))

            with httpx.Client(
                follow_redirects=True,
                timeout=15,
                headers=_get_headers(),
            ) as client:
                response = client.get(url)
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Title
            title_el = soup.select_one("#productTitle")
            if title_el:
                info.title = title_el.get_text(strip=True)

            # Brand
            brand_el = soup.select_one("#bylineInfo") or soup.select_one(
                'a[id="bylineInfo"]'
            )
            if brand_el:
                brand_text = brand_el.get_text(strip=True)
                # Clean "Visit the X Store" or "Brand: X" patterns
                brand_text = re.sub(r"^(Visit the |Brand:\s*)", "", brand_text)
                brand_text = re.sub(r"\s*Store$", "", brand_text)
                info.brand = brand_text

            # Category — from breadcrumbs
            breadcrumbs = soup.select("#wayfinding-breadcrumbs_feature_div li a")
            if breadcrumbs:
                info.category = breadcrumbs[-1].get_text(strip=True)

            # Main image
            img_el = soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")
            if img_el:
                info.image_url = img_el.get("src") or img_el.get("data-old-hires")

            # Price
            price_el = soup.select_one("span.a-price .a-offscreen")
            if price_el:
                info.price = price_el.get_text(strip=True)

            logger.info("Scraped product %s: %s", asin, info.title)
            return info

        except httpx.HTTPStatusError as e:
            logger.warning(
                "HTTP %d scraping %s (attempt %d/%d)",
                e.response.status_code,
                asin,
                attempt + 1,
                retries,
            )
            if e.response.status_code == 503 or e.response.status_code == 429:
                # Blocked — wait longer before retrying
                time.sleep(random.uniform(10, 20) * (attempt + 1))
            elif attempt == retries - 1:
                raise
        except httpx.HTTPError as e:
            logger.warning(
                "Network error scraping %s (attempt %d/%d): %s",
                asin,
                attempt + 1,
                retries,
                e,
            )
            if attempt == retries - 1:
                raise
            time.sleep(random.uniform(3, 8) * (attempt + 1))

    return info


def validate_affiliate_url(url: str) -> bool:
    """Check if a URL looks like a valid Amazon affiliate/product link."""
    url = url.strip().lower()
    amazon_domains = [
        "amazon.com",
        "amazon.co.uk",
        "amazon.ca",
        "amazon.de",
        "amazon.co.jp",
        "amzn.to",
        "a.co",
    ]
    return any(domain in url for domain in amazon_domains)
