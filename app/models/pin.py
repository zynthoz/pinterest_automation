"""Pin model — represents a Pinterest pin (draft, scheduled, or published)."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PinStatus:
    """Pin lifecycle statuses."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class Pin(Base):
    __tablename__ = "pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tiktok_videos.id", ondelete="CASCADE"), nullable=False
    )
    pinterest_pin_id: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[str | None] = mapped_column(Text)  # comma-separated
    alt_text: Mapped[str | None] = mapped_column(String(500))
    board_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PinStatus.DRAFT, index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    product = relationship("Product", back_populates="pins")
    video = relationship("TikTokVideo", back_populates="pins")

    def __repr__(self) -> str:
        return f"<Pin(id={self.id}, status={self.status!r}, title={self.title!r})>"
