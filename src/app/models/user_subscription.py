from datetime import UTC, datetime
from sqlalchemy import ForeignKey, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.db.database import Base
from .tier import Tier
from .user import User

class UserSubscription(Base):
    __tablename__ = "user_subscription"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    tier_id: Mapped[int] = mapped_column(ForeignKey("tier.id"), index=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    
    # Track usage
    campaigns_used: Mapped[int] = mapped_column(Integer, default=0)
    campaigns_created_this_month: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    tier: Mapped["Tier"] = relationship(back_populates="subscriptions")