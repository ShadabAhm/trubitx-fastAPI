from pydantic import BaseModel
from typing import Dict, Any

class CampaignLimitsResponse(BaseModel):
    max_campaigns: int
    max_competitors: int
    max_duration_days: int
    max_articles_per_campaign: int
    campaigns_created: int
    campaigns_remaining: int
    tier_name: str
    has_active_tier: bool