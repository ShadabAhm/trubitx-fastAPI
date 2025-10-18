from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class CampaignBase(BaseModel):
    name: str
    brand_keyword: str
    competitors: List[str]
    regions: List[str]
    duration_days: int = Field(default=14, ge=1, le=30)
    form_data: Dict[str, Any] = Field(default_factory=dict)
    is_recurring: bool = False
    interval_hours: Optional[int] = Field(default=None, ge=1, le=168)  # 1 hour to 7 days


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[int] = None
    form_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    is_recurring: Optional[bool] = None
    interval_hours: Optional[int] = Field(default=None, ge=1, le=168)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None


class CampaignRead(CampaignBase):
    id: int
    user_id: int
    status: str
    current_step: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CampaignJobBase(BaseModel):
    status: str
    progress: int = Field(ge=0, le=100)
    current_stage: Optional[str] = None
    error_log: Optional[str] = None


class CampaignJobRead(CampaignJobBase):
    id: UUID
    campaign_id: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArticleBase(BaseModel):
    engine: str
    market: str
    query: str
    title: str
    summary: str
    link: str
    orig_link: str
    domain: str
    published_at: datetime
    rank_in_feed: int
    body: Optional[str] = None


class ArticleRead(ArticleBase):
    id: int
    campaign_id: int
    title_key: Optional[str] = None
    row_id: Optional[str] = None
    sentiment: float
    position_w: float
    est_ars: float
    pickup_count: int
    inferred_clicks: float
    engagement_rate: float
    tier: str
    is_aggregator: bool
    match_score: float
    created_at: datetime

    class Config:
        from_attributes = True


class BrandKPIBase(BaseModel):
    brand: str
    mentions: int
    weighted_reach: float
    avg_sentiment: float
    avg_engagement_rate: float
    avg_pickup_rate: float
    inferred_clicks: float
    share_of_voice: float
    ad_equivalent_value_inr: float


class BrandKPIRead(BrandKPIBase):
    id: int
    campaign_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class PublicationKPIBase(BaseModel):
    domain: str
    mentions: int
    weighted_reach: float
    avg_engagement_rate: float
    avg_sentiment: float
    tier: str
    is_aggregator: bool


class PublicationKPIRead(PublicationKPIBase):
    id: int
    campaign_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class GenericKeywordAnalysisBase(BaseModel):
    brand: str
    generic_keyword_mentions: int
    positive_generic_mentions: int
    positive_rate: float


class GenericKeywordAnalysisRead(GenericKeywordAnalysisBase):
    id: int
    campaign_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CampaignWithJob(CampaignRead):
    job_status: Optional[str] = None
    job_progress: Optional[int] = None
    job_current_stage: Optional[str] = None


class CampaignStatusResponse(BaseModel):
    campaign_status: str
    job_status: str
    progress: int
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    estimated_time_remaining: str


class CampaignResultsResponse(BaseModel):
    brand_kpis: List[BrandKPIRead]
    publication_kpis: List[PublicationKPIRead]
    articles: List[ArticleRead]
    generic_analysis: List[GenericKeywordAnalysisRead]
    summary: Dict[str, Any]