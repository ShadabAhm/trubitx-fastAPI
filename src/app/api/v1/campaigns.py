from typing import Annotated, Any, List
import logging
from datetime import datetime, UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response
from fastcrud.paginated import PaginatedListResponse, compute_offset, paginated_response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..dependencies import get_current_user, get_current_superuser
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import DuplicateValueException, NotFoundException, ForbiddenException
from ...crud import crud_campaign, crud_campaign_job
from ...schemas import (
    CampaignCreate, CampaignRead, CampaignUpdate, CampaignWithJob,
    CampaignStatusResponse, CampaignResultsResponse, CampaignJobRead
)
from ...schemas.campaign_limits import CampaignLimitsResponse
from ...services.pr_kpi_service import PRKPIService
from ...services.subscription_service import SubscriptionService
from ...services.report_service import ReportService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["campaigns"])


@router.get("/campaign/limits", response_model=CampaignLimitsResponse)
async def get_campaign_limits(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> CampaignLimitsResponse:
    """
    Get user's campaign limits based on their tier.
    Note: This route MUST be defined before /campaign/{campaign_id} to avoid path conflicts.
    """
    subscription_service = SubscriptionService(db)
    limits = await subscription_service.get_user_limits(current_user["id"])
    return CampaignLimitsResponse(**limits)


@router.post("/campaign", status_code=201)
async def create_campaign(
    campaign: CampaignCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> CampaignRead:
    """
    Create a new PR campaign and start background processing
    """
    subscription_service = SubscriptionService(db)

    # Single validation call that checks all tier limits (removed duplicate can_create_campaign check)
    campaign_data = campaign.model_dump()
    await subscription_service.validate_campaign_creation(current_user["id"], campaign_data)

    # Use a savepoint for transaction safety
    try:
        # Create campaign
        created_campaign = await crud_campaign.create(db=db, user_id=current_user["id"], campaign_in=campaign)

        # Create campaign job
        await crud_campaign_job.create(db=db, campaign_id=created_campaign.id)

        # Increment campaign count
        await subscription_service.increment_campaign_count(current_user["id"])

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create campaign: {e}")
        raise HTTPException(status_code=500, detail="Failed to create campaign. Please try again.")

    # Start background processing (outside transaction)
    background_tasks.add_task(execute_campaign_background, created_campaign.id)

    return CampaignRead.model_validate(created_campaign)


@router.get("/campaigns", response_model=PaginatedListResponse[CampaignWithJob])
async def read_campaigns(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    items_per_page: int = 10
) -> dict:
    """
    Get paginated list of user's campaigns
    """
    campaigns_data = await crud_campaign.get_user_campaigns(
        db=db,
        user_id=current_user["id"],
        skip=compute_offset(page, items_per_page),
        limit=items_per_page
    )

    # Get total count for pagination
    total_count = await crud_campaign.count_user_campaigns(
        db=db,
        user_id=current_user["id"]
    )

    # Enhance with job data
    enhanced_campaigns = []
    for campaign in campaigns_data:
        campaign_dict = CampaignRead.model_validate(campaign).model_dump()
        if campaign.job:
            campaign_dict["job_status"] = campaign.job.status
            campaign_dict["job_progress"] = campaign.job.progress
            campaign_dict["job_current_stage"] = campaign.job.current_stage
        enhanced_campaigns.append(campaign_dict)

    response: dict[str, Any] = paginated_response(
        crud_data={"data": enhanced_campaigns, "total_count": total_count},
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/campaign/{campaign_id}", response_model=CampaignWithJob)
async def read_campaign(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> CampaignWithJob:
    """
    Get specific campaign details
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    campaign_dict = CampaignRead.model_validate(campaign).model_dump()
    if campaign.job:
        campaign_dict["job_status"] = campaign.job.status
        campaign_dict["job_progress"] = campaign.job.progress
        campaign_dict["job_current_stage"] = campaign.job.current_stage
    
    return CampaignWithJob.model_validate(campaign_dict)


@router.get("/campaign/{campaign_id}/status", response_model=CampaignStatusResponse)
async def get_campaign_status(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> CampaignStatusResponse:
    """
    Get campaign processing status and progress
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    job = await crud_campaign_job.get_by_campaign_id(db=db, campaign_id=campaign_id)
    if job is None:
        raise NotFoundException("Campaign job not found")
    
    estimated_time = estimate_time_remaining(job.progress)
    
    return CampaignStatusResponse(
        campaign_status=campaign.status,
        job_status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        error_message=campaign.error_message,
        estimated_time_remaining=estimated_time
    )


@router.get("/campaign/{campaign_id}/results", response_model=CampaignResultsResponse)
async def get_campaign_results(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> CampaignResultsResponse:
    """
    Get campaign results (available when campaign has data, regardless of status)
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    # Get all related data
    from sqlalchemy import select
    from ...models import Article, BrandKPI, PublicationKPI, GenericKeywordAnalysis
    
    # Brand KPIs
    brand_kpis_result = await db.execute(select(BrandKPI).where(BrandKPI.campaign_id == campaign.id))
    brand_kpis = brand_kpis_result.scalars().all()

    # Publication KPIs
    pub_kpis_result = await db.execute(select(PublicationKPI).where(PublicationKPI.campaign_id == campaign.id))
    pub_kpis = pub_kpis_result.scalars().all()

    # Articles
    articles_result = await db.execute(select(Article).where(Article.campaign_id == campaign.id))
    articles = articles_result.scalars().all()

    # Generic Analysis
    generic_analysis_result = await db.execute(select(GenericKeywordAnalysis).where(GenericKeywordAnalysis.campaign_id == campaign.id))
    generic_analysis = generic_analysis_result.scalars().all()
    
    # Check if we have any data
    has_data = any([
        len(brand_kpis) > 0,
        len(pub_kpis) > 0, 
        len(articles) > 0,
        len(generic_analysis) > 0
    ])
    
    if not has_data:
        # For recurring campaigns that are active/paused but haven't run yet
        if campaign.status in ['active', 'paused'] and campaign.is_recurring:
            raise HTTPException(
                status_code=400,
                detail="No data available yet. The recurring campaign hasn't completed its first run."
            )
        # For one-time campaigns that are still processing
        elif campaign.status in ['in_progress', 'ingesting']:
            raise HTTPException(
                status_code=400,
                detail="Campaign is still processing. Please check back later when data is available."
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="No data available for this campaign."
            )
    
    # Summary
    summary = {
        'total_articles': len(articles),
        'total_mentions': sum(kpi.mentions for kpi in brand_kpis) if brand_kpis else 0,
        'total_reach': sum(kpi.weighted_reach for kpi in brand_kpis) if brand_kpis else 0,
        'campaign_duration_days': campaign.duration_days,
        'regions': campaign.regions,
        'competitors_analyzed': len(campaign.competitors),
        'campaign_name': campaign.name,
        'created_at': campaign.created_at,
        'campaign_status': campaign.status,
        'is_recurring': campaign.is_recurring,
        'last_run_at': campaign.last_run_at
    }
    
    return CampaignResultsResponse(
        brand_kpis=brand_kpis,
        publication_kpis=pub_kpis,
        articles=articles,
        generic_analysis=generic_analysis,
        summary=summary
    )


@router.post("/campaign/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, str]:
    """
    Cancel a running or paused campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    if campaign.status not in ['in_progress', 'paused', 'ingesting']:
        raise HTTPException(status_code=400, detail="Cannot cancel completed or errored campaign")
    
    # Update campaign status
    await crud_campaign.update(db=db, campaign_id=campaign_id, campaign_in=CampaignUpdate(status='cancelled'))
    
    # Update job status
    await crud_campaign_job.update_status(db=db, campaign_id=campaign_id, status='cancelled')
    
    return {"message": "Campaign cancelled successfully"}


@router.delete("/campaign/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, str]:
    """
    Soft delete a campaign (sets is_deleted=True instead of removing from database)
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")

    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")

    success = await crud_campaign.soft_delete(db=db, campaign_id=campaign_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete campaign")

    return {"message": "Campaign deleted successfully"}


@router.post("/campaign/{campaign_id}/toggle-recurring")
async def toggle_recurring(
    campaign_id: int,
    interval_hours: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, Any]:
    """
    Toggle recurring mode for a campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")

    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")

    # Validate interval_hours
    if interval_hours < 1 or interval_hours > 168:
        raise HTTPException(status_code=400, detail="Interval must be between 1 and 168 hours")

    # Toggle recurring
    new_recurring_state = not campaign.is_recurring
    update_data = {
        "is_recurring": new_recurring_state,
        "interval_hours": interval_hours if new_recurring_state else None
    }

    # Set next_run_at if enabling recurring
    if new_recurring_state:
        update_data["next_run_at"] = datetime.now(UTC) + timedelta(hours=interval_hours)
        update_data["status"] = "active"
    else:
        update_data["next_run_at"] = None

    await crud_campaign.update(db=db, campaign_id=campaign_id, campaign_in=CampaignUpdate(**update_data))

    return {
        "message": f"Recurring mode {'enabled' if new_recurring_state else 'disabled'}",
        "is_recurring": new_recurring_state,
        "interval_hours": interval_hours if new_recurring_state else None,
        "next_run_at": update_data.get("next_run_at")
    }


@router.put("/campaign/{campaign_id}/interval")
async def update_interval(
    campaign_id: int,
    interval_hours: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, Any]:
    """
    Update the interval hours for a recurring campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")

    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")

    if not campaign.is_recurring:
        raise HTTPException(status_code=400, detail="Campaign is not set to recurring mode")

    # Validate interval_hours
    if interval_hours < 1 or interval_hours > 168:
        raise HTTPException(status_code=400, detail="Interval must be between 1 and 168 hours")

    # Update interval and recalculate next_run_at
    base_time = campaign.last_run_at if campaign.last_run_at else datetime.now(UTC)
    next_run_at = base_time + timedelta(hours=interval_hours)

    await crud_campaign.update(
        db=db,
        campaign_id=campaign_id,
        campaign_in=CampaignUpdate(interval_hours=interval_hours, next_run_at=next_run_at)
    )

    return {
        "message": "Interval updated successfully",
        "interval_hours": interval_hours,
        "next_run_at": next_run_at
    }


@router.get("/campaign/{campaign_id}/runs")
async def get_campaign_runs(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, Any]:
    """
    Get run history and schedule for a campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")

    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "is_recurring": campaign.is_recurring,
        "interval_hours": campaign.interval_hours,
        "last_run_at": campaign.last_run_at,
        "next_run_at": campaign.next_run_at,
        "created_at": campaign.created_at,
        "status": campaign.status
    }


@router.get("/campaign/{campaign_id}/report")
async def download_campaign_report(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> Response:
    """
    Generate and download PDF report for a completed campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")

    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")

    if campaign.status != 'completed' and campaign.status != 'active':
        raise HTTPException(
            status_code=400,
            detail="Report only available for completed or active campaigns with data"
        )

    # Generate PDF report
    report_service = ReportService(db, campaign_id)
    pdf_bytes = await report_service.generate_pdf_report()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=campaign_{campaign_id}_report.pdf"
        }
    )


# ========== BACKGROUND TASK FUNCTIONS ==========

async def execute_campaign_background(campaign_id: int):
    """Background task to execute campaign processing with proper error handling"""
    from ...core.db.database import async_session_factory

    async with async_session_factory() as session:
        try:
            # Update job status to in_progress
            await crud_campaign_job.update_status(db=session, campaign_id=campaign_id, status='in_progress')

            service = PRKPIService(session, campaign_id)
            await service.execute_campaign()

            # Job status is already updated to 'completed' by the service
            # Campaign status is also updated by the service:
            # - 'active' for recurring campaigns
            # - 'completed' for non-recurring campaigns
            # No need to update status here as the service handles it correctly

        except Exception as e:
            logger.error(f"Background campaign execution failed for campaign {campaign_id}: {e}", exc_info=True)
            # Update campaign and job status to failed
            try:
                await crud_campaign_job.update_status(
                    db=session,
                    campaign_id=campaign_id,
                    status='failed',
                    error_log=str(e)
                )
                await crud_campaign.update(
                    db=session,
                    campaign_id=campaign_id,
                    campaign_in=CampaignUpdate(status='failed', error_message=str(e))
                )
            except Exception as update_error:
                logger.error(f"Failed to update campaign status after error: {update_error}")


async def resume_campaign_background(campaign_id: int):
    """Background task to resume campaign processing with proper error handling"""
    from ...core.db.database import async_session_factory

    async with async_session_factory() as session:
        try:
            # Update job status to in_progress
            await crud_campaign_job.update_status(db=session, campaign_id=campaign_id, status='in_progress')

            service = PRKPIService(session, campaign_id)
            await service.execute_campaign()

            # Job status is already updated to 'completed' by the service
            # Campaign status is also updated by the service:
            # - 'active' for recurring campaigns
            # - 'completed' for non-recurring campaigns
            # No need to update status here as the service handles it correctly

        except Exception as e:
            logger.error(f"Background campaign resumption failed for campaign {campaign_id}: {e}", exc_info=True)
            try:
                await crud_campaign_job.update_status(
                    db=session,
                    campaign_id=campaign_id,
                    status='failed',
                    error_log=str(e)
                )
                await crud_campaign.update(
                    db=session,
                    campaign_id=campaign_id,
                    campaign_in=CampaignUpdate(status='failed', error_message=str(e))
                )
            except Exception as update_error:
                logger.error(f"Failed to update campaign status after error: {update_error}")


# ========== HELPER FUNCTIONS ==========

def estimate_time_remaining(progress: int) -> str:
    """Simple time estimation based on progress"""
    if progress == 0:
        return "Calculating..."
    elif progress < 20:
        return "15-20 minutes remaining"
    elif progress < 40:
        return "10-15 minutes remaining"
    elif progress < 60:
        return "8-12 minutes remaining"
    elif progress < 80:
        return "5-8 minutes remaining"
    elif progress < 95:
        return "2-5 minutes remaining"
    else:
        return "Almost complete"