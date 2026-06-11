"""TikTok video model — represents a downloaded TikTok video linked to a product."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TikTokVideo(Base):
    __tablename__ = "tiktok_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_url: Mapped[str] = mapped_column(Text, nullable=False)
    creator_username: Mapped[str] = mapped_column(String(200), nullable=False)
    creator_profile_url: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    view_count: Mapped[int | None] = mapped_column(Integer)
    local_path: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    product = relationship("Product", back_populates="tiktok_videos")
    pins = relationship("Pin", back_populates="video", cascade="all, delete")

    def __repr__(self) -> str:
        return (
            f"<TikTokVideo(id={self.id}, creator=@{self.creator_username!r}, "
            f"views={self.view_count})>"
        )
