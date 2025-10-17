from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from fastapi import HTTPException
from datetime import UTC, datetime

from ..models.pr_campaign import Campaign, CampaignJob, Article, BrandKPI, PublicationKPI, GenericKeywordAnalysis
from ..schemas.pr_campaign import CampaignCreate, CampaignUpdate


class CRUDCampaign:
    async def create(
        self, 
        db: AsyncSession, 
        user_id: int, 
        campaign_in: CampaignCreate
    ) -> Campaign:
        campaign_data = campaign_in.model_dump()
        campaign = Campaign(user_id=user_id, **campaign_data)
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        return campaign

    async def get_by_id(self, db: AsyncSession, campaign_id: int) -> Optional[Campaign]:
        result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        return result.scalar_one_or_none()

    async def get_user_campaigns(
        self,
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[Campaign]:
        result = await db.execute(
            select(Campaign)
            .where(Campaign.user_id == user_id)
            .offset(skip)
            .limit(limit)
            .order_by(Campaign.created_at.desc())
        )
        return result.scalars().all()

    async def count_user_campaigns(self, db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count(Campaign.id)).where(Campaign.user_id == user_id)
        )
        return result.scalar_one()

    async def update(
        self,
        db: AsyncSession,
        campaign_id: int,
        campaign_in: CampaignUpdate
    ) -> Campaign:
        update_data = campaign_in.model_dump(exclude_unset=True)
        if update_data:
            await db.execute(
                update(Campaign)
                .where(Campaign.id == campaign_id)
                .values(**update_data, updated_at=datetime.now(UTC))
            )
            await db.commit()

        campaign = await self.get_by_id(db, campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return campaign

    async def delete(self, db: AsyncSession, campaign_id: int) -> bool:
        result = await db.execute(delete(Campaign).where(Campaign.id == campaign_id))
        await db.commit()
        return result.rowcount > 0


class CRUDCampaignJob:
    async def create(self, db: AsyncSession, campaign_id: int) -> CampaignJob:
        job = CampaignJob(campaign_id=campaign_id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    async def get_by_campaign_id(self, db: AsyncSession, campaign_id: int) -> Optional[CampaignJob]:
        result = await db.execute(select(CampaignJob).where(CampaignJob.campaign_id == campaign_id))
        return result.scalar_one_or_none()

    async def update_progress(
        self,
        db: AsyncSession,
        campaign_id: int,
        progress: int,
        stage: Optional[str] = None
    ) -> CampaignJob:
        update_data = {"progress": progress}
        if stage:
            update_data["current_stage"] = stage

        await db.execute(
            update(CampaignJob)
            .where(CampaignJob.campaign_id == campaign_id)
            .values(**update_data)
        )
        await db.commit()

        job = await self.get_by_campaign_id(db, campaign_id)
        if not job:
            raise HTTPException(status_code=404, detail="Campaign job not found")
        return job

    async def update_status(
        self,
        db: AsyncSession,
        campaign_id: int,
        status: str,
        error_log: Optional[str] = None
    ) -> CampaignJob:
        update_data = {"status": status}
        if status in ['in_progress']:
            update_data["started_at"] = datetime.now(UTC)
        elif status in ['completed', 'failed']:
            update_data["completed_at"] = datetime.now(UTC)
        if error_log:
            update_data["error_log"] = error_log

        await db.execute(
            update(CampaignJob)
            .where(CampaignJob.campaign_id == campaign_id)
            .values(**update_data)
        )
        await db.commit()

        job = await self.get_by_campaign_id(db, campaign_id)
        if not job:
            raise HTTPException(status_code=404, detail="Campaign job not found")
        return job


# Initialize CRUD instances
crud_campaign = CRUDCampaign()
crud_campaign_job = CRUDCampaignJob()