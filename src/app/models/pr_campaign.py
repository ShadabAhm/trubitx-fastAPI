from datetime import UTC, datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING
import uuid
from ..core.db.database import Base

if TYPE_CHECKING:
    from .user import User


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    brand_keyword: Mapped[str] = mapped_column(Text)
    competitors: Mapped[list] = mapped_column(JSON)
    regions: Mapped[list] = mapped_column(JSON)
    duration_days: Mapped[int] = mapped_column(Integer, default=14)
    status: Mapped[str] = mapped_column(String(20), default='ingesting')
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Recurring campaign fields
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="campaigns")
    job: Mapped["CampaignJob"] = relationship("CampaignJob", back_populates="campaign", uselist=False)
    articles: Mapped[list] = relationship("Article", back_populates="campaign")
    brand_kpis: Mapped[list] = relationship("BrandKPI", back_populates="campaign")
    publication_kpis: Mapped[list] = relationship("PublicationKPI", back_populates="campaign")
    generic_analyses: Mapped[list] = relationship("GenericKeywordAnalysis", back_populates="campaign")


class CampaignJob(Base):
    __tablename__ = "campaign_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Relationships
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="job")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    
    engine: Mapped[str] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(10))
    query: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(Text)
    orig_link: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rank_in_feed: Mapped[int] = mapped_column(Integer)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    row_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    position_w: Mapped[float] = mapped_column(Float, default=1.0)
    est_ars: Mapped[float] = mapped_column(Float, default=0.0)
    pickup_count: Mapped[int] = mapped_column(Integer, default=0)
    inferred_clicks: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    tier: Mapped[str] = mapped_column(String(20), default='tier2')
    is_aggregator: Mapped[bool] = mapped_column(Boolean, default=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="articles")


class BrandKPI(Base):
    __tablename__ = "brand_kpis"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    brand: Mapped[str] = mapped_column(String(255))
    mentions: Mapped[int] = mapped_column(Integer)
    weighted_reach: Mapped[float] = mapped_column(Float)
    avg_sentiment: Mapped[float] = mapped_column(Float)
    avg_engagement_rate: Mapped[float] = mapped_column(Float)
    avg_pickup_rate: Mapped[float] = mapped_column(Float)
    inferred_clicks: Mapped[float] = mapped_column(Float)
    share_of_voice: Mapped[float] = mapped_column(Float)
    ad_equivalent_value_inr: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="brand_kpis")


class PublicationKPI(Base):
    __tablename__ = "publication_kpis"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    domain: Mapped[str] = mapped_column(String(255))
    mentions: Mapped[int] = mapped_column(Integer)
    weighted_reach: Mapped[float] = mapped_column(Float)
    avg_engagement_rate: Mapped[float] = mapped_column(Float)
    avg_sentiment: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(20))
    is_aggregator: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="publication_kpis")


class GenericKeywordAnalysis(Base):
    __tablename__ = "generic_keyword_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    brand: Mapped[str] = mapped_column(String(255))
    generic_keyword_mentions: Mapped[int] = mapped_column(Integer)
    positive_generic_mentions: Mapped[int] = mapped_column(Integer)
    positive_rate: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="generic_analyses")
