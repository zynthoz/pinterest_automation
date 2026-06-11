"""Pydantic schemas for job-related requests and responses."""

from datetime import datetime

from pydantic import BaseModel


class JobResponse(BaseModel):
    """Job status returned in API responses."""

    id: int
    product_id: int | None = None
    affiliate_url: str
    celery_task_id: str | None = None
    status: str
    current_step: str | None = None
    error: str | None = None
    result_pin_id: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    product_title: str | None = None
    product_image: str | None = None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """Paginated list of jobs."""

    jobs: list[JobResponse]
    total: int
    page: int
    per_page: int
