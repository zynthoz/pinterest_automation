"""Celery tasks for Pinterest pin publishing."""

import logging
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.pin import Pin, PinStatus
from app.models.product import Product
from app.models.tiktok_video import TikTokVideo
from app.services.pinterest import PinterestClient, PinterestAPIError
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.pinterest_tasks.publish_pin",
    max_retries=2,
    default_retry_delay=60,
)
def publish_pin(self, job_id: int, pin_id: int) -> dict:
    """
    Upload video and publish pin to Pinterest.

    Returns:
        dict with pinterest_pin_id
    """
    db = SessionLocal()
    client = None
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.PUBLISHING
        job.current_step = "Publishing pin to Pinterest"
        db.commit()

        pin = db.query(Pin).filter(Pin.id == pin_id).first()
        if not pin:
            raise ValueError(f"Pin {pin_id} not found")

        video = db.query(TikTokVideo).filter(TikTokVideo.id == pin.video_id).first()
        product = db.query(Product).filter(Product.id == pin.product_id).first()

        if not video or not video.local_path:
            raise ValueError("Video file not found or not downloaded")
        if not product:
            raise ValueError("Product not found")

        # Build description with hashtags
        description = pin.description
        if pin.hashtags:
            hashtag_str = " ".join(f"#{h.strip()}" for h in pin.hashtags.split(","))
            description = f"{description}\n\n{hashtag_str}"

        # Publish to Pinterest
        client = PinterestClient()
        pin.status = PinStatus.PUBLISHING
        db.commit()

        result = client.create_video_pin(
            video_path=video.local_path,
            board_id=pin.board_id,
            title=pin.title,
            description=description,
            link=product.affiliate_url,
            alt_text=pin.alt_text,
        )

        # Update pin with Pinterest response
        pin.pinterest_pin_id = result.get("id")
        pin.status = PinStatus.PUBLISHED
        pin.posted_at = datetime.now(timezone.utc)
        pin.error = None

        # Mark job complete
        job.status = JobStatus.COMPLETED
        job.current_step = "Pin published successfully"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Published pin %d → Pinterest ID: %s", pin.id, pin.pinterest_pin_id)
        return {"pinterest_pin_id": pin.pinterest_pin_id}

    except PinterestAPIError as exc:
        db.rollback()
        if exc.status_code == 429:
            # Rate limited — retry with longer delay
            _update_pin_status(db, pin_id, PinStatus.SCHEDULED)
            raise self.retry(exc=exc, countdown=120)
        _mark_failed(db, job_id, str(exc))
        _update_pin_status(db, pin_id, PinStatus.FAILED, str(exc))
        raise self.retry(exc=exc) if self.request.retries < self.max_retries else exc
    except Exception as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
        _update_pin_status(db, pin_id, PinStatus.FAILED, str(exc))
        raise self.retry(exc=exc) if self.request.retries < self.max_retries else exc
    finally:
        if client:
            client.close()
        db.close()


@celery_app.task(name="app.workers.pinterest_tasks.process_scheduled_pins")
def process_scheduled_pins():
    """
    Periodic task: check for pins scheduled to post now and publish them.

    Called by Celery Beat every 60 seconds.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        scheduled_pins = (
            db.query(Pin)
            .filter(
                Pin.status == PinStatus.SCHEDULED,
                Pin.scheduled_at <= now,
            )
            .all()
        )

        for pin in scheduled_pins:
            # Find or create a job for this pin
            job = (
                db.query(Job)
                .filter(Job.result_pin_id == pin.id, Job.status != JobStatus.FAILED)
                .first()
            )
            if job:
                publish_pin.delay(job.id, pin.id)
                logger.info("Dispatched scheduled pin %d for publishing", pin.id)

    except Exception as e:
        logger.error("Error processing scheduled pins: %s", e)
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


def _update_pin_status(db, pin_id: int, status: str, error: str | None = None):
    """Update pin status."""
    try:
        pin = db.query(Pin).filter(Pin.id == pin_id).first()
        if pin:
            pin.status = status
            if error:
                pin.error = error[:1000]
            db.commit()
    except Exception:
        db.rollback()
