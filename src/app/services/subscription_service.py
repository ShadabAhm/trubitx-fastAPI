from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from ..models.user import User
from ..models.tier import Tier

class SubscriptionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_limits(self, user_id: int) -> Dict[str, Any]:
        """Get user's campaign limits based on their tier"""
        result = await self.db.execute(
            select(User, Tier).join(Tier, User.tier_id == Tier.id).where(User.id == user_id)
        )
        user_tier = result.first()
        
        if not user_tier:
            # User has no tier - return free tier limits
            return {
                "max_campaigns": 1,
                "max_competitors": 1,
                "max_duration_days": 7,
                "max_articles_per_campaign": 50,
                "campaigns_created": 0,
                "campaigns_remaining": 1,
                "tier_name": "Free",
                "has_active_tier": False
            }
        
        user, tier = user_tier
        campaigns_remaining = max(0, tier.max_campaigns - user.campaigns_created)
        
        return {
            "max_campaigns": tier.max_campaigns,
            "max_competitors": tier.max_competitors,
            "max_duration_days": tier.max_duration_days,
            "max_articles_per_campaign": tier.max_articles_per_campaign,
            "campaigns_created": user.campaigns_created,
            "campaigns_remaining": campaigns_remaining,
            "tier_name": tier.name,
            "has_active_tier": True
        }

    async def validate_campaign_creation(self, user_id: int, campaign_data: Dict[str, Any]) -> bool:
        """Validate if user can create a campaign based on their tier limits"""
        limits = await self.get_user_limits(user_id)
        
        # Check campaign count limit
        if limits["campaigns_created"] >= limits["max_campaigns"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Campaign limit reached. Your {limits['tier_name']} plan allows {limits['max_campaigns']} campaigns."
            )
        
        # Check competitors limit
        competitors_count = len(campaign_data.get("competitors", []))
        if competitors_count > limits["max_competitors"]:
            raise HTTPException(
                status_code=400,
                detail=f"Too many competitors. Your {limits['tier_name']} plan allows {limits['max_competitors']} competitors."
            )
        
        # Check duration limit
        duration_days = campaign_data.get("duration_days", 14)
        if duration_days > limits["max_duration_days"]:
            raise HTTPException(
                status_code=400,
                detail=f"Duration too long. Your {limits['tier_name']} plan allows up to {limits['max_duration_days']} days."
            )
        
        return True

    async def increment_campaign_count(self, user_id: int) -> bool:
        """Increment user's campaign count when they create a new campaign"""
        from sqlalchemy import update
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                campaigns_created=User.campaigns_created + 1,
                campaigns_created_this_month=User.campaigns_created_this_month + 1
            )
        )
        await self.db.commit()
        return True

    async def can_create_campaign(self, user_id: int) -> bool:
        """Check if user can create a new campaign"""
        limits = await self.get_user_limits(user_id)
        return limits["campaigns_created"] < limits["max_campaigns"]

    async def reset_monthly_usage(self):
        """Reset monthly usage counters (to be called by a scheduled task)"""
        from sqlalchemy import update
        await self.db.execute(
            update(User).values(campaigns_created_this_month=0)
        )
        await self.db.commit()