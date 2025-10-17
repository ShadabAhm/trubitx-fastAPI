from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class TierBase(BaseModel):
    name: str
    price: str
    duration: Optional[str] = None
    description: str
    sub_description: Optional[str] = None
    features: List[str]
    button_text: str
    button_variant: str = "primary"
    highlighted: bool = False
    badge: Optional[str] = None
    
    # PR Campaign Limits
    max_campaigns: int = Field(default=3, ge=1)
    max_competitors: int = Field(default=2, ge=1, le=10)
    max_duration_days: int = Field(default=14, ge=1, le=30)
    max_articles_per_campaign: int = Field(default=100, ge=10, le=1000)

class TierCreate(TierBase):
    pass

class TierCreateInternal(TierBase):
    pass

class TierUpdate(BaseModel):
    price: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None
    sub_description: Optional[str] = None
    features: Optional[List[str]] = None
    button_text: Optional[str] = None
    button_variant: Optional[str] = None
    highlighted: Optional[bool] = None
    badge: Optional[str] = None
    
    # PR Campaign Limits (optional updates)
    max_campaigns: Optional[int] = Field(None, ge=1)
    max_competitors: Optional[int] = Field(None, ge=1, le=10)
    max_duration_days: Optional[int] = Field(None, ge=1, le=30)
    max_articles_per_campaign: Optional[int] = Field(None, ge=10, le=1000)

class TierRead(TierBase):
    id: int

    class Config:
        from_attributes = True

class TierUpdateInternal(TierUpdate):
    updated_at: datetime

class TierDelete(BaseModel):
    pass