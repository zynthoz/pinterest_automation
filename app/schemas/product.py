"""Pydantic schemas for product-related requests and responses."""

from datetime import datetime

from pydantic import BaseModel, HttpUrl


class ProductCreate(BaseModel):
    """Request body for submitting a single affiliate URL."""

    affiliate_url: str


class ProductBulkCreate(BaseModel):
    """Request body for submitting multiple affiliate URLs at once."""

    affiliate_urls: list[str]


class ProductResponse(BaseModel):
    """Product data returned in API responses."""

    id: int
    asin: str
    affiliate_url: str
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    image_url: str | None = None
    price: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
