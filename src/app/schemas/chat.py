# schemas/chat.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional, Dict, Any

class ChatRequest(BaseModel):
    message: str
    campaign_id: Optional[int] = None

class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    timestamp: datetime

class CampaignSummary(BaseModel):
    total_campaigns: int
    active_campaigns: int
    completed_campaigns: int
    total_mentions: int
    total_reach: int
    total_articles: int
    llm_summary: str
    campaigns: List[Dict[str, Any]]