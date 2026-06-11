"""Job model — tracks the pipeline execution for a single product."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus:
    """Job lifecycle statuses — tracks which pipeline step is active."""

    QUEUED = "queued"
    EXTRACTING = "extracting"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    GENERATING = "generating"
    SCHEDULING = "scheduling"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"

    ALL_STEPS = [QUEUED, EXTRACTING, SEARCHING, DOWNLOADING, GENERATING, SCHEDULING, PUBLISHING]


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    affiliate_url: Mapped[str] = mapped_column(Text, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.QUEUED, index=True
    )
    current_step: Mapped[str | None] = mapped_column(String(50))
    error: Mapped[str | None] = mapped_column(Text)
    result_pin_id: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    product = relationship("Product", back_populates="jobs")

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, status={self.status!r}, url={self.affiliate_url!r})>"
