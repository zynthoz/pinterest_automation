"""Product model — represents an Amazon product extracted from an affiliate link."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asin: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    affiliate_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(200))
    image_url: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tiktok_videos = relationship("TikTokVideo", back_populates="product", cascade="all, delete")
    pins = relationship("Pin", back_populates="product", cascade="all, delete")
    jobs = relationship("Job", back_populates="product", cascade="all, delete")

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, asin={self.asin!r}, title={self.title!r})>"
