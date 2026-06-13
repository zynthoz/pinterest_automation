"""Celery tasks for AI copy generation."""

import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.pin import Pin, PinStatus
from app.models.product import Product
from app.models.tiktok_video import TikTokVideo
from app.services.ai_copy import generate_pin_copy
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.ai_tasks.generate_copy",
    max_retries=3,
    default_retry_delay=5,
)
def generate_copy(self, job_id: int, product_id: int, video_id: int) -> dict:
    """
    Generate AI-optimized pin copy and create a draft Pin record.

    Returns:
        dict with pin_id
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.GENERATING
        job.current_step = "Generating AI copy with Gemini"
        db.commit()

        product = db.query(Product).filter(Product.id == product_id).first()
        video = db.query(TikTokVideo).filter(TikTokVideo.id == video_id).first()

        if not product or not video:
            raise ValueError("Product or video not found")

        # Check if copy was already generated
        if job.result_pin_id:
            existing_pin = db.query(Pin).filter(Pin.id == job.result_pin_id).first()
            if existing_pin:
                logger.info("AI copy already generated. Using existing Pin ID %d", existing_pin.id)
                return {"pin_id": existing_pin.id}

        # Generate copy via Gemini
        copy = generate_pin_copy(
            product_title=product.title,
            product_brand=product.brand,
            product_category=product.category,
            product_price=product.price,
            creator_username=video.creator_username,
            tiktok_caption=video.caption,
        )

        # Create draft pin record
        board_id = settings.pinterest_board_name or settings.pinterest_board_id
        if not board_id:
            raise ValueError("Neither PINTEREST_BOARD_NAME nor PINTEREST_BOARD_ID is set in .env")

        pin = Pin(
            product_id=product_id,
            video_id=video_id,
            title=copy["title"],
            description=copy["description"],
            hashtags=copy["hashtags"],
            alt_text=copy["alt_text"],
            board_id=board_id,
            status=PinStatus.DRAFT,
        )
        db.add(pin)
        db.flush()

        job.result_pin_id = pin.id
        db.commit()

        logger.info("Generated copy for pin %d: %s", pin.id, copy["title"])
        return {"pin_id": pin.id}

    except Exception as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
        raise self.retry(exc=exc) if self.request.retries < self.max_retries else exc
    finally:
        db.close()


def _mark_failed(db, job_id: int, error: str):
    """Mark a job as failed."""
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error = error[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
