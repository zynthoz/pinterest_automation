"""Pipeline orchestration — chains Celery tasks into a full workflow.

Flow: extract_product → search_tiktok → download_video → generate_copy → publish/schedule_pin
"""

import logging
from datetime import datetime, timezone

from celery import chain

from app.config import settings
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.pin import Pin, PinStatus
from app.services.scheduler import calculate_next_slot
from app.workers.celery_app import celery_app
from app.workers.product_tasks import extract_product
from app.workers.tiktok_tasks import search_tiktok, download_tiktok_video
from app.workers.ai_tasks import generate_copy
from app.workers.pinterest_tasks import publish_pin

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.pipeline.run_pipeline",
)
def run_pipeline(self, job_id: int):
    """
    Execute the full pin creation pipeline for a single job.

    Each step passes results to the next via Celery task chaining.
    On failure at any step, the job is marked as failed.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        logger.info("Starting pipeline for job %d: %s", job_id, job.affiliate_url)

        # Step 1: Extract product
        product_result = extract_product(job_id)
        product_id = product_result["product_id"]
        asin = product_result["asin"]

        # Step 2: Search TikTok
        search_result = search_tiktok(job_id, product_id)
        video_id = search_result["selected_video_id"]

        # Step 3: Download video
        download_result = download_tiktok_video(job_id, video_id, asin)

        # Step 4: Generate AI copy
        copy_result = generate_copy(job_id, product_id, video_id)
        pin_id = copy_result["pin_id"]

        # Step 5: Schedule or publish
        schedule_or_publish(job_id, pin_id)

        logger.info("Pipeline completed for job %d", job_id)

    except Exception as exc:
        logger.error("Pipeline failed for job %d: %s", job_id, exc, exc_info=True)
        _mark_failed(db, job_id, str(exc))
    finally:
        db.close()


@celery_app.task(name="app.workers.pipeline.schedule_or_publish")
def schedule_or_publish(job_id: int, pin_id: int):
    """
    Publish the pin immediately.
    """
    logger.info("Publishing pin %d immediately", pin_id)
    publish_pin(job_id, pin_id)


@celery_app.task(name="app.workers.pipeline.retry_failed_jobs")
def retry_failed_jobs():
    """
    Periodic task: automatically retry recently failed jobs.

    Only retries jobs that failed within the last hour and haven't
    been retried more than 3 times.
    """
    db = SessionLocal()
    try:
        one_hour_ago = datetime.now(timezone.utc).replace(
            microsecond=0
        ) - __import__("datetime").timedelta(hours=1)

        failed_jobs = (
            db.query(Job)
            .filter(
                Job.status == JobStatus.FAILED,
                Job.completed_at >= one_hour_ago,
            )
            .all()
        )

        for job in failed_jobs:
            # Reset job for retry
            job.status = JobStatus.QUEUED
            job.error = None
            job.completed_at = None
            job.current_step = "Retrying..."
            db.commit()

            run_pipeline.delay(job.id)
            logger.info("Retrying failed job %d", job.id)

    except Exception as e:
        logger.error("Error in retry_failed_jobs: %s", e)
        db.rollback()
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
