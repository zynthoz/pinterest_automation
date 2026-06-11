"""Product API routes — submit affiliate URLs and trigger pipeline."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job, JobStatus
from app.schemas.product import ProductCreate, ProductBulkCreate
from app.schemas.job import JobResponse
from app.services.amazon import validate_affiliate_url
from app.workers.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])


@router.post("", response_model=JobResponse)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """
    Submit a single Amazon affiliate URL.

    Creates a job and kicks off the full pipeline asynchronously.
    """
    url = payload.affiliate_url.strip()

    if not validate_affiliate_url(url):
        raise HTTPException(status_code=400, detail="Not a valid Amazon URL")

    # Create job
    job = Job(affiliate_url=url, status=JobStatus.QUEUED)
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch pipeline
    task = run_pipeline.delay(job.id)
    job.celery_task_id = task.id
    db.commit()

    logger.info("Created job %d for URL: %s", job.id, url)

    return JobResponse(
        id=job.id,
        affiliate_url=job.affiliate_url,
        celery_task_id=job.celery_task_id,
        status=job.status,
        current_step=job.current_step,
        started_at=job.started_at,
    )


@router.post("/bulk", response_model=list[JobResponse])
def create_products_bulk(payload: ProductBulkCreate, db: Session = Depends(get_db)):
    """
    Submit multiple Amazon affiliate URLs at once.

    Creates a job for each URL and queues them all.
    """
    results = []
    errors = []

    for url in payload.affiliate_urls:
        url = url.strip()
        if not url:
            continue

        if not validate_affiliate_url(url):
            errors.append(f"Invalid URL skipped: {url}")
            continue

        job = Job(affiliate_url=url, status=JobStatus.QUEUED)
        db.add(job)
        db.flush()

        task = run_pipeline.delay(job.id)
        job.celery_task_id = task.id

        results.append(
            JobResponse(
                id=job.id,
                affiliate_url=job.affiliate_url,
                celery_task_id=job.celery_task_id,
                status=job.status,
                started_at=job.started_at,
            )
        )

    db.commit()

    if errors:
        logger.warning("Bulk create had %d errors: %s", len(errors), errors)

    logger.info("Created %d jobs from bulk submission", len(results))
    return results
