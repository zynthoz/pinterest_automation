"""Celery tasks for TikTok search and video download."""

import logging
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.product import Product
from app.models.tiktok_video import TikTokVideo
from app.services.tiktok.downloader import download_video
from app.services.tiktok.playwright_provider import (
    PlaywrightTikTokProvider,
    build_search_query,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tiktok_tasks.search_tiktok",
    max_retries=2,
    default_retry_delay=15,
)
def search_tiktok(self, job_id: int, product_id: int) -> dict:
    """
    Search TikTok for product-related videos and auto-pick the best one.

    Saves all results to DB and marks the highest-view-count video as selected.

    Returns:
        dict with selected_video_id
    """
    db = SessionLocal()
    provider = None
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.SEARCHING
        job.current_step = "Searching TikTok for product videos"
        db.commit()

        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise ValueError(f"Product {product_id} not found")

        # Build search query
        query = build_search_query(product.brand, product.title)
        logger.info("TikTok search query: %s", query)

        # Search using Playwright provider
        provider = PlaywrightTikTokProvider()
        results = provider.search(query, max_results=10)

        if not results:
            raise ValueError(f"No TikTok videos found for query: {query}")

        # Save all results to DB
        selected_video = None
        for i, result in enumerate(results):
            video = TikTokVideo(
                product_id=product_id,
                video_url=result.video_url,
                creator_username=result.creator_username,
                creator_profile_url=result.creator_profile_url,
                caption=result.caption,
                view_count=result.view_count,
                selected=(i == 0),  # Auto-pick: first result (highest views)
            )
            db.add(video)
            if i == 0:
                db.flush()
                selected_video = video

        db.commit()

        logger.info(
            "Found %d videos. Auto-selected: @%s (%d views)",
            len(results),
            selected_video.creator_username,
            selected_video.view_count or 0,
        )

        return {"selected_video_id": selected_video.id}

    except Exception as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
        raise self.retry(exc=exc) if self.request.retries < self.max_retries else exc
    finally:
        if provider:
            provider.close()
        db.close()


@celery_app.task(
    bind=True,
    name="app.workers.tiktok_tasks.download_tiktok_video",
    max_retries=2,
    default_retry_delay=10,
)
def download_tiktok_video(self, job_id: int, video_id: int, asin: str) -> dict:
    """
    Download the selected TikTok video to local filesystem.

    Returns:
        dict with local_path and duration_seconds
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.DOWNLOADING
        job.current_step = "Downloading TikTok video"
        db.commit()

        video = db.query(TikTokVideo).filter(TikTokVideo.id == video_id).first()
        if not video:
            raise ValueError(f"TikTokVideo {video_id} not found")

        # Download the video
        result = download_video(video.video_url, asin)

        # Update video record with local path
        video.local_path = result["local_path"]
        video.duration_seconds = result["duration_seconds"]
        db.commit()

        logger.info("Downloaded video to: %s", result["local_path"])
        return {
            "local_path": result["local_path"],
            "duration_seconds": result["duration_seconds"],
            "video_id": video_id,
        }

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
