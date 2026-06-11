"""Pydantic schemas for pin-related requests and responses."""

from datetime import datetime

from pydantic import BaseModel


class PinResponse(BaseModel):
    """Pin data returned in API responses."""

    id: int
    product_id: int
    video_id: int
    pinterest_pin_id: str | None = None
    title: str
    description: str
    hashtags: str | None = None
    alt_text: str | None = None
    board_id: str
    status: str
    scheduled_at: datetime | None = None
    posted_at: datetime | None = None
    error: str | None = None
    created_at: datetime

    # Joined fields
    product_title: str | None = None
    product_image: str | None = None
    affiliate_url: str | None = None
    creator_username: str | None = None

    model_config = {"from_attributes": True}


class PinListResponse(BaseModel):
    """Paginated list of pins."""

    pins: list[PinResponse]
    total: int
    page: int
    per_page: int
