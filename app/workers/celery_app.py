"""Celery application instance and configuration."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "pinterest_automation",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone=settings.timezone,
    enable_utc=True,

    # Retry policy
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # Result expiry (24 hours)
    result_expires=86400,

    # Task routes — all tasks go to default queue
    task_default_queue="pinterest",

    # Autodiscover tasks in workers package
    include=[
        "app.workers.product_tasks",
        "app.workers.tiktok_tasks",
        "app.workers.ai_tasks",
        "app.workers.pinterest_tasks",
        "app.workers.pipeline",
    ],

    # Beat schedule for periodic tasks (Phase 2)
    beat_schedule={},
)
