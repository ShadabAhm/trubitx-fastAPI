from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

class UserSubscriptionBase(BaseModel):
    user_id: int
    tier_id: int
    is_active: bool = True
    start_date: datetime
    end_date: datetime
    campaigns_used: int = 0
    campaigns_created_this_month: int = 0

class UserSubscriptionCreate(UserSubscriptionBase):
    pass

class UserSubscriptionCreateInternal(UserSubscriptionBase):
    pass

class UserSubscriptionUpdate(BaseModel):
    is_active: Optional[bool] = None
    campaigns_used: Optional[int] = None
    campaigns_created_this_month: Optional[int] = None
    end_date: Optional[datetime] = None

class UserSubscriptionRead(UserSubscriptionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class UserSubscriptionWithTier(UserSubscriptionRead):
    tier: 'TierRead'

class UserSubscriptionDelete(BaseModel):
    pass