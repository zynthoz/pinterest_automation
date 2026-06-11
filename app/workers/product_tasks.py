"""Celery tasks for Amazon product extraction."""

import logging
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.product import Product
from app.services.amazon import extract_asin, scrape_product, validate_affiliate_url
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.product_tasks.extract_product",
    max_retries=3,
    default_retry_delay=10,
)
def extract_product(self, job_id: int) -> dict:
    """
    Extract ASIN from affiliate URL and scrape product info.

    Updates job status and creates/updates the Product record.

    Returns:
        dict with product_id and asin
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Update job status
        job.status = JobStatus.EXTRACTING
        job.current_step = "Extracting product info from Amazon"
        db.commit()

        url = job.affiliate_url

        # Validate URL
        if not validate_affiliate_url(url):
            raise ValueError(f"Not a valid Amazon URL: {url}")

        # Extract ASIN
        asin = extract_asin(url)
        if not asin:
            raise ValueError(f"Could not extract ASIN from: {url}")

        # Check if product already exists
        existing = db.query(Product).filter(Product.asin == asin).first()
        if existing:
            job.product_id = existing.id
            db.commit()
            logger.info("Product already exists: %s (ID: %d)", asin, existing.id)
            return {"product_id": existing.id, "asin": asin}

        # Scrape product info
        info = scrape_product(asin)

        # Create product record
        product = Product(
            asin=info.asin,
            affiliate_url=url,
            title=info.title,
            brand=info.brand,
            category=info.category,
            image_url=info.image_url,
            price=info.price,
        )
        db.add(product)
        db.flush()

        job.product_id = product.id
        db.commit()

        logger.info("Extracted product: %s — %s", asin, info.title)
        return {"product_id": product.id, "asin": asin}

    except Exception as exc:
        db.rollback()
        _mark_failed(db, job_id, str(exc))
        raise self.retry(exc=exc) if self.request.retries < self.max_retries else exc
    finally:
        db.close()


def _mark_failed(db, job_id: int, error: str):
    """Mark a job as failed with error message."""
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error = error[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
