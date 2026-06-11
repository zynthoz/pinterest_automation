"""AI copy generation using Google Gemini API.

Generates Pinterest-optimized titles, descriptions, hashtags, and alt-text
from product info and TikTok video context.
"""

import json
import logging
import re

from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are a Pinterest marketing expert specializing in product affiliate content.
Generate optimized Pinterest pin content for this product.

Product Information:
- Title: {product_title}
- Brand: {product_brand}
- Category: {product_category}
- Price: {product_price}

TikTok Video Context:
- Creator: @{creator_username}
- Caption: {tiktok_caption}

Requirements:
1. **title**: Pinterest-optimized title (max 100 characters). Must be keyword-rich, engaging, and NOT clickbait. Include the product name/type.

2. **description**: Pinterest-optimized description (300-500 characters).
   - Include a compelling call-to-action
   - Include relevant SEO keywords naturally
   - MUST end with these two lines (include them exactly):
     "{ftc_disclosure}"
     "Video credit: @{creator_username} on TikTok"

3. **hashtags**: Array of 5-10 relevant hashtags (without the # symbol). Mix product-specific and trending Pinterest hashtags.

4. **alt_text**: Concise accessibility description of the product/video content (max 200 characters).

Tone: helpful, aspirational, authentic. Write as if recommending to a friend.

Respond ONLY with valid JSON in this exact format:
{{
  "title": "...",
  "description": "...",
  "hashtags": ["tag1", "tag2", ...],
  "alt_text": "..."
}}"""


def generate_pin_copy(
    product_title: str,
    product_brand: str | None,
    product_category: str | None,
    product_price: str | None,
    creator_username: str,
    tiktok_caption: str | None,
    max_retries: int = 3,
) -> dict:
    """
    Generate Pinterest pin copy using Gemini API.

    Args:
        product_title: Amazon product title
        product_brand: Product brand name
        product_category: Product category
        product_price: Product price string
        creator_username: TikTok creator handle
        tiktok_caption: Original TikTok video caption
        max_retries: Max retry attempts for malformed responses

    Returns:
        dict with keys: title, description, hashtags (str), alt_text

    Raises:
        RuntimeError: if AI generation fails after all retries
    """
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    client = genai.Client(api_key=settings.gemini_api_key)

    prompt = PROMPT_TEMPLATE.format(
        product_title=product_title or "Unknown Product",
        product_brand=product_brand or "Unknown",
        product_category=product_category or "General",
        product_price=product_price or "N/A",
        creator_username=creator_username,
        tiktok_caption=tiktok_caption or "No caption available",
        ftc_disclosure=settings.ftc_disclosure,
    )

    for attempt in range(max_retries):
        try:
            logger.info(
                "Generating AI copy (attempt %d/%d, model: %s)",
                attempt + 1,
                max_retries,
                settings.gemini_model,
            )

            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
            )

            raw_text = response.text.strip()

            # Clean markdown code fences if present
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

            data = json.loads(raw_text)

            # Validate required fields
            result = _validate_and_clean(data, creator_username)
            logger.info("Generated pin title: %s", result["title"])
            return result

        except json.JSONDecodeError as e:
            logger.warning(
                "Gemini returned invalid JSON (attempt %d): %s\nRaw: %s",
                attempt + 1,
                e,
                raw_text[:500],
            )
        except Exception as e:
            logger.warning("Gemini API error (attempt %d): %s", attempt + 1, e)

    raise RuntimeError(f"AI copy generation failed after {max_retries} attempts")


def _validate_and_clean(data: dict, creator_username: str) -> dict:
    """Validate AI output and enforce constraints."""
    title = str(data.get("title", ""))[:100]
    description = str(data.get("description", ""))
    alt_text = str(data.get("alt_text", ""))[:200]

    # Ensure hashtags are a list of strings
    hashtags_raw = data.get("hashtags", [])
    if isinstance(hashtags_raw, list):
        hashtags = [str(h).strip().lstrip("#") for h in hashtags_raw[:10]]
    else:
        hashtags = [h.strip().lstrip("#") for h in str(hashtags_raw).split(",")][:10]

    # Ensure FTC disclosure is in description
    if settings.ftc_disclosure not in description:
        description = f"{description}\n\n{settings.ftc_disclosure}"

    # Ensure creator credit is in description
    credit_line = f"Video credit: @{creator_username} on TikTok"
    if credit_line not in description and creator_username not in description:
        description = f"{description}\n{credit_line}"

    # Enforce description length (trim from middle if too long, keep end intact)
    if len(description) > 500:
        # Keep the last ~100 chars (disclosure + credit) intact
        core = description[:400]
        suffix = description[len(description) - 100 :]
        description = core.rstrip() + "\n\n" + suffix.lstrip()

    return {
        "title": title,
        "description": description,
        "hashtags": ", ".join(hashtags),
        "alt_text": alt_text,
    }
