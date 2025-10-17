from datetime import UTC, datetime
from sqlalchemy import String, JSON, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.db.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .user import User

class Tier(Base):
    __tablename__ = "tier"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    price: Mapped[str] = mapped_column(String(50))
    duration: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String(255))
    sub_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    features: Mapped[list] = mapped_column(JSON)
    button_text: Mapped[str] = mapped_column(String(100))
    badge: Mapped[str | None] = mapped_column(String(50), nullable=True)
    button_variant: Mapped[str] = mapped_column(String(20), default="primary")
    highlighted: Mapped[bool] = mapped_column(Boolean, default=False)
    
    max_campaigns: Mapped[int] = mapped_column(Integer, default=3)
    max_competitors: Mapped[int] = mapped_column(Integer, default=2)
    max_duration_days: Mapped[int] = mapped_column(Integer, default=14)
    max_articles_per_campaign: Mapped[int] = mapped_column(Integer, default=100)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    users: Mapped[list] = relationship("User", back_populates="tier")
    subscriptions: Mapped[list] = relationship("UserSubscription", back_populates="tier")

