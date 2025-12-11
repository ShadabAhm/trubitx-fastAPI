from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from datetime import UTC, datetime

from ..models.pr_campaign import Campaign, CampaignJob, Article, BrandKPI, PublicationKPI, GenericKeywordAnalysis
from ..schemas.pr_campaign import CampaignCreate, CampaignUpdate
from ..core.exceptions.http_exceptions import NotFoundException


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
        """Get campaign by ID (excludes soft-deleted campaigns)"""
        result = await db.execute(
            select(Campaign)
            .options(selectinload(Campaign.job))
            .where(Campaign.id == campaign_id)
            .where(Campaign.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_user_campaigns(
        self,
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool = False
    ) -> List[Campaign]:
        """Get user's campaigns (excludes soft-deleted by default)"""
        query = (
            select(Campaign)
            .options(selectinload(Campaign.job))
            .where(Campaign.user_id == user_id)
        )
        if not include_deleted:
            query = query.where(Campaign.is_deleted == False)

        result = await db.execute(
            query.offset(skip)
            .limit(limit)
            .order_by(Campaign.created_at.desc())
        )
        return result.scalars().all()

    async def count_user_campaigns(self, db: AsyncSession, user_id: int, include_deleted: bool = False) -> int:
        """Count user's campaigns (excludes soft-deleted by default)"""
        query = select(func.count(Campaign.id)).where(Campaign.user_id == user_id)
        if not include_deleted:
            query = query.where(Campaign.is_deleted == False)
        result = await db.execute(query)
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
                .where(Campaign.is_deleted == False)
                .values(**update_data, updated_at=datetime.now(UTC))
            )
            await db.commit()

        campaign = await self.get_by_id(db, campaign_id)
        if not campaign:
            raise NotFoundException("Campaign not found")
        return campaign

    async def soft_delete(self, db: AsyncSession, campaign_id: int) -> bool:
        """Soft delete a campaign by setting is_deleted=True"""
        result = await db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .where(Campaign.is_deleted == False)
            .values(
                is_deleted=True,
                deleted_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
        )
        await db.commit()
        return result.rowcount > 0

    async def hard_delete(self, db: AsyncSession, campaign_id: int) -> bool:
        """Permanently delete a campaign and all related records (use with caution)"""
        # Delete related records first (cascade delete)
        await db.execute(delete(Article).where(Article.campaign_id == campaign_id))
        await db.execute(delete(BrandKPI).where(BrandKPI.campaign_id == campaign_id))
        await db.execute(delete(PublicationKPI).where(PublicationKPI.campaign_id == campaign_id))
        await db.execute(delete(GenericKeywordAnalysis).where(GenericKeywordAnalysis.campaign_id == campaign_id))
        await db.execute(delete(CampaignJob).where(CampaignJob.campaign_id == campaign_id))
        result = await db.execute(delete(Campaign).where(Campaign.id == campaign_id))
        await db.commit()
        return result.rowcount > 0

    async def restore(self, db: AsyncSession, campaign_id: int) -> bool:
        """Restore a soft-deleted campaign"""
        result = await db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .where(Campaign.is_deleted == True)
            .values(
                is_deleted=False,
                deleted_at=None,
                updated_at=datetime.now(UTC)
            )
        )
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
            raise NotFoundException("Campaign job not found")
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
            raise NotFoundException("Campaign job not found")
        return job


# Initialize CRUD instances
crud_campaign = CRUDCampaign()
crud_campaign_job = CRUDCampaignJob()