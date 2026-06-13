"""Celery tasks for Pinterest pin publishing via Playwright."""

import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.pin import Pin, PinStatus
from app.models.product import Product
from app.models.tiktok_video import TikTokVideo
from app.services.pinterest_poster import PinterestPoster, PinterestPostError
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.pinterest_tasks.publish_pin",
    max_retries=0,
)
def publish_pin(self, job_id: int, pin_id: int) -> dict:
    """
    Upload video and publish pin to Pinterest.

    Returns:
        dict with pinterest_pin_id
    """
    db = SessionLocal()
    poster = None
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

        # Publish to Pinterest via Playwright browser automation
        board_name = settings.pinterest_board_name or pin.board_id
        
        def on_progress(message: str):
            try:
                job.current_step = message
                db.commit()
            except Exception as e:
                logger.warning("Failed to update progress: %s", e)

        poster = PinterestPoster()
        pin.status = PinStatus.PUBLISHING
        db.commit()

        result = poster.create_pin(
            media_path=video.local_path,
            title=pin.title,
            description=description,
            link=product.affiliate_url,
            board_name=board_name,
            on_progress=on_progress,
        )

        if not result.get("success"):
            raise PinterestPostError(
                result.get("message", "Unknown error"),
                step="publish",
            )

        # Update pin with result
        pin_url = result.get("pin_url")
        if pin_url:
            import re
            match = re.search(r'/pin/(\d+)', pin_url)
            if match:
                pin.pinterest_pin_id = match.group(1)
            elif pin_url.isdigit():
                pin.pinterest_pin_id = pin_url
            else:
                pin.pinterest_pin_id = pin_url
        else:
            pin.pinterest_pin_id = None
        pin.status = PinStatus.PUBLISHED
        pin.posted_at = datetime.now(timezone.utc)
        pin.error = None

        # Mark job complete
        job.status = JobStatus.COMPLETED
        job.current_step = "Pin published successfully"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Published pin %d → %s", pin.id, pin.pinterest_pin_id)

        # Clean up local video file to free disk space
        _cleanup_video_file(video)
        db.commit()

        return {"pinterest_pin_id": pin.pinterest_pin_id}

    except PinterestPostError as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
        _update_pin_status(db, pin_id, PinStatus.FAILED, str(exc))
        raise exc
    except Exception as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
        _update_pin_status(db, pin_id, PinStatus.FAILED, str(exc))
        raise exc
    finally:
        if poster:
            poster.close()
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


def _cleanup_video_file(video) -> None:
    """Delete the local video file from disk after a successful publish.

    Clears ``video.local_path`` so the DB doesn't hold a stale reference.
    Errors are logged but never raised — cleanup failures must never break
    the publish success flow.
    """
    from pathlib import Path

    if not video or not video.local_path:
        return

    path = Path(video.local_path)
    try:
        if path.exists():
            path.unlink()
            logger.info("Deleted local video file after publish: %s", path)
        else:
            logger.debug("Video file already gone (skipping delete): %s", path)
        video.local_path = None
    except Exception as exc:
        logger.warning("Could not delete local video file %s: %s", path, exc)
