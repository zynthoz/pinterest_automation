"""Pin API routes — view and manage Pinterest pins."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pin import Pin, PinStatus
from app.models.product import Product
from app.models.tiktok_video import TikTokVideo
from app.schemas.pin import PinResponse, PinListResponse
from app.services.pinterest import PinterestClient, PinterestAPIError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pins", tags=["pins"])


@router.get("", response_model=PinListResponse)
def list_pins(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List all pins, optionally filtered by status."""
    query = db.query(Pin)

    if status:
        query = query.filter(Pin.status == status)

    total = query.count()
    pins = (
        query.order_by(Pin.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    pin_responses = []
    for pin in pins:
        product = db.query(Product).filter(Product.id == pin.product_id).first()
        video = db.query(TikTokVideo).filter(TikTokVideo.id == pin.video_id).first()

        pin_responses.append(
            PinResponse(
                id=pin.id,
                product_id=pin.product_id,
                video_id=pin.video_id,
                pinterest_pin_id=pin.pinterest_pin_id,
                title=pin.title,
                description=pin.description,
                hashtags=pin.hashtags,
                alt_text=pin.alt_text,
                board_id=pin.board_id,
                status=pin.status,
                scheduled_at=pin.scheduled_at,
                posted_at=pin.posted_at,
                error=pin.error,
                created_at=pin.created_at,
                product_title=product.title if product else None,
                product_image=product.image_url if product else None,
                affiliate_url=product.affiliate_url if product else None,
                creator_username=video.creator_username if video else None,
            )
        )

    return PinListResponse(
        pins=pin_responses,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{pin_id}", response_model=PinResponse)
def get_pin(pin_id: int, db: Session = Depends(get_db)):
    """Get a single pin with full details."""
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    product = db.query(Product).filter(Product.id == pin.product_id).first()
    video = db.query(TikTokVideo).filter(TikTokVideo.id == pin.video_id).first()

    return PinResponse(
        id=pin.id,
        product_id=pin.product_id,
        video_id=pin.video_id,
        pinterest_pin_id=pin.pinterest_pin_id,
        title=pin.title,
        description=pin.description,
        hashtags=pin.hashtags,
        alt_text=pin.alt_text,
        board_id=pin.board_id,
        status=pin.status,
        scheduled_at=pin.scheduled_at,
        posted_at=pin.posted_at,
        error=pin.error,
        created_at=pin.created_at,
        product_title=product.title if product else None,
        product_image=product.image_url if product else None,
        affiliate_url=product.affiliate_url if product else None,
        creator_username=video.creator_username if video else None,
    )


@router.delete("/{pin_id}")
def delete_pin(pin_id: int, db: Session = Depends(get_db)):
    """Delete a pin from the database and optionally from Pinterest."""
    pin = db.query(Pin).filter(Pin.id == pin_id).first()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    # Try to delete from Pinterest if published
    if pin.pinterest_pin_id:
        try:
            import re
            pin_id_to_delete = pin.pinterest_pin_id
            match = re.search(r'/pin/(\d+)', pin_id_to_delete)
            if match:
                pin_id_to_delete = match.group(1)
            elif not pin_id_to_delete.isdigit():
                digits = re.findall(r'\d+', pin_id_to_delete)
                if digits:
                    pin_id_to_delete = digits[-1]

            client = PinterestClient()
            client.delete_pin(pin_id_to_delete)
            client.close()
        except PinterestAPIError as e:
            logger.warning("Failed to delete pin from Pinterest: %s", e)

    db.delete(pin)
    db.commit()

    return {"detail": f"Pin {pin_id} deleted"}
