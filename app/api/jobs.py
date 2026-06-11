"""Job API routes — view job status and manage jobs."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job, JobStatus
from app.models.product import Product
from app.schemas.job import JobResponse, JobListResponse
from app.workers.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List all jobs, optionally filtered by status. Most recent first."""
    query = db.query(Job)

    if status:
        query = query.filter(Job.status == status)

    total = query.count()
    jobs = (
        query.order_by(Job.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    job_responses = []
    for job in jobs:
        product = db.query(Product).filter(Product.id == job.product_id).first() if job.product_id else None
        job_responses.append(
            JobResponse(
                id=job.id,
                product_id=job.product_id,
                affiliate_url=job.affiliate_url,
                celery_task_id=job.celery_task_id,
                status=job.status,
                current_step=job.current_step,
                error=job.error,
                result_pin_id=job.result_pin_id,
                started_at=job.started_at,
                completed_at=job.completed_at,
                product_title=product.title if product else None,
                product_image=product.image_url if product else None,
            )
        )

    return JobListResponse(
        jobs=job_responses,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get a single job with full details."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    product = db.query(Product).filter(Product.id == job.product_id).first() if job.product_id else None

    return JobResponse(
        id=job.id,
        product_id=job.product_id,
        affiliate_url=job.affiliate_url,
        celery_task_id=job.celery_task_id,
        status=job.status,
        current_step=job.current_step,
        error=job.error,
        result_pin_id=job.result_pin_id,
        started_at=job.started_at,
        completed_at=job.completed_at,
        product_title=product.title if product else None,
        product_image=product.image_url if product else None,
    )


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: int, db: Session = Depends(get_db)):
    """Retry a failed job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")

    # Reset job
    job.status = JobStatus.QUEUED
    job.error = None
    job.completed_at = None
    job.current_step = "Retrying..."
    db.commit()

    # Re-dispatch pipeline
    task = run_pipeline.delay(job.id)
    job.celery_task_id = task.id
    db.commit()
    db.refresh(job)

    logger.info("Retrying job %d", job_id)

    return JobResponse(
        id=job.id,
        product_id=job.product_id,
        affiliate_url=job.affiliate_url,
        celery_task_id=job.celery_task_id,
        status=job.status,
        current_step=job.current_step,
        started_at=job.started_at,
    )
