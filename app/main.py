"""FastAPI application entry point.

Serves the Jinja2 dashboard and JSON API routes.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db, get_db, SessionLocal
from app.models.job import Job, JobStatus
from app.models.pin import Pin, PinStatus
from app.models.product import Product

# API routers
from app.api.products import router as products_router
from app.api.jobs import router as jobs_router
from app.api.pins import router as pins_router
from app.api.pinterest_auth import router as auth_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup and shutdown events."""
    # Startup
    logger.info("Initializing database...")
    init_db()
    settings.downloads_path  # ensure downloads dir exists
    logger.info("Pinterest Automation Tool ready!")
    logger.info("Dashboard: http://%s:%d", settings.host, settings.port)
    yield
    # Shutdown
    logger.info("Shutting down...")


# Create app
app = FastAPI(
    title="Pinterest Automation",
    description="Automated Pinterest pin creation from Amazon affiliate links",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(exist_ok=True)
(STATIC_DIR / "js").mkdir(exist_ok=True)
(STATIC_DIR / "img").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API routers
app.include_router(products_router)
app.include_router(jobs_router)
app.include_router(pins_router)
app.include_router(auth_router)


# ─── Page Routes (Jinja2 HTML) ──────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    db = SessionLocal()
    try:
        # Quick stats
        total_jobs = db.query(Job).count()
        active_jobs = db.query(Job).filter(
            Job.status.notin_([JobStatus.COMPLETED, JobStatus.FAILED])
        ).count()
        completed_jobs = db.query(Job).filter(Job.status == JobStatus.COMPLETED).count()
        failed_jobs = db.query(Job).filter(Job.status == JobStatus.FAILED).count()

        published_pins = db.query(Pin).filter(Pin.status == PinStatus.PUBLISHED).count()
        scheduled_pins = db.query(Pin).filter(Pin.status == PinStatus.SCHEDULED).count()

        # Recent jobs
        recent_jobs = (
            db.query(Job)
            .order_by(Job.started_at.desc())
            .limit(20)
            .all()
        )

        # Enrich with product info
        jobs_data = []
        for job in recent_jobs:
            product = db.query(Product).filter(Product.id == job.product_id).first() if job.product_id else None
            jobs_data.append({
                "id": job.id,
                "affiliate_url": job.affiliate_url,
                "status": job.status,
                "current_step": job.current_step,
                "error": job.error,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
                "product_title": product.title if product else None,
                "product_image": product.image_url if product else None,
            })

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            context={
                "stats": {
                    "total_jobs": total_jobs,
                    "active_jobs": active_jobs,
                    "completed_jobs": completed_jobs,
                    "failed_jobs": failed_jobs,
                    "published_pins": published_pins,
                    "scheduled_pins": scheduled_pins,
                },
                "jobs": jobs_data,
                "pinterest_connected": bool(settings.pinterest_access_token),
            },
        )
    finally:
        db.close()


@app.get("/pins", response_class=HTMLResponse)
async def pins_page(request: Request):
    """Pin history and management page."""
    db = SessionLocal()
    try:
        pins = db.query(Pin).order_by(Pin.created_at.desc()).limit(50).all()
        pins_data = []
        for pin in pins:
            product = db.query(Product).filter(Product.id == pin.product_id).first()
            pins_data.append({
                "id": pin.id,
                "title": pin.title,
                "description": pin.description,
                "hashtags": pin.hashtags,
                "status": pin.status,
                "pinterest_pin_id": pin.pinterest_pin_id,
                "scheduled_at": pin.scheduled_at,
                "posted_at": pin.posted_at,
                "error": pin.error,
                "product_title": product.title if product else None,
                "product_image": product.image_url if product else None,
                "affiliate_url": product.affiliate_url if product else None,
            })

        return templates.TemplateResponse(
            request,
            "pins.html",
            context={
                "pins": pins_data,
            },
        )
    finally:
        db.close()


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings and configuration page."""
    return templates.TemplateResponse(
        request,
        "settings.html",
        context={
            "pinterest_connected": bool(settings.pinterest_access_token),
            "pinterest_board_id": settings.pinterest_board_id,
            "pins_per_day_min": settings.pins_per_day_min,
            "pins_per_day_max": settings.pins_per_day_max,
            "schedule_start_hour": settings.schedule_start_hour,
            "schedule_end_hour": settings.schedule_end_hour,
            "timezone": settings.timezone,
            "gemini_model": settings.gemini_model,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
