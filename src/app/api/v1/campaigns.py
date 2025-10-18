from typing import Annotated, Any, List
import asyncio
from datetime import datetime, UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response
from fastcrud.paginated import PaginatedListResponse, compute_offset, paginated_response
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter(tags=["campaigns"])


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
    # Validate tier limits
    subscription_service = SubscriptionService(db)
    
    # Check if user can create campaign
    if not await subscription_service.can_create_campaign(current_user["id"]):
        limits = await subscription_service.get_user_limits(current_user["id"])
        raise HTTPException(
            status_code=400,
            detail=f"Campaign limit reached. Your {limits['tier_name']} plan allows {limits['max_campaigns']} campaigns. You've used {limits['campaigns_created']}."
        )
    
    # Validate campaign parameters against tier limits
    campaign_data = campaign.model_dump()
    await subscription_service.validate_campaign_creation(current_user["id"], campaign_data)
    
    # Create campaign
    created_campaign = await crud_campaign.create(db=db, user_id=current_user["id"], campaign_in=campaign)
    
    # Create campaign job
    await crud_campaign_job.create(db=db, campaign_id=created_campaign.id)
    
    # Increment campaign count
    await subscription_service.increment_campaign_count(current_user["id"])
    
    # Start background processing
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
    Get campaign results (only available when campaign is completed)
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    if campaign.status != 'completed':
        raise HTTPException(status_code=400, detail="Campaign not completed yet")
    
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
    
    # Summary
    summary = {
        'total_articles': len(articles),
        'total_mentions': sum(kpi.mentions for kpi in brand_kpis),
        'total_reach': sum(kpi.weighted_reach for kpi in brand_kpis),
        'campaign_duration_days': campaign.duration_days,
        'regions': campaign.regions,
        'competitors_analyzed': len(campaign.competitors),
        'campaign_name': campaign.name,
        'created_at': campaign.created_at
    }
    
    return CampaignResultsResponse(
        brand_kpis=brand_kpis,
        publication_kpis=pub_kpis,
        articles=articles,
        generic_analysis=generic_analysis,
        summary=summary
    )


@router.post("/campaign/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, str]:
    """
    Pause a running campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    if campaign.status != 'in_progress':
        raise HTTPException(status_code=400, detail="Only campaigns in progress can be paused")
    
    # Update campaign status
    await crud_campaign.update(db=db, campaign_id=campaign_id, campaign_in=CampaignUpdate(status='paused'))
    
    # Update job status
    await crud_campaign_job.update_status(db=db, campaign_id=campaign_id, status='paused')
    
    return {"message": "Campaign paused successfully"}


@router.post("/campaign/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict[str, str]:
    """
    Resume a paused campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    if campaign.status != 'paused':
        raise HTTPException(status_code=400, detail="Only paused campaigns can be resumed")
    
    # Update campaign status
    await crud_campaign.update(db=db, campaign_id=campaign_id, campaign_in=CampaignUpdate(status='in_progress'))
    
    # Update job status
    await crud_campaign_job.update_status(db=db, campaign_id=campaign_id, status='in_progress')
    
    # Restart background processing from where it left off
    background_tasks.add_task(resume_campaign_background, campaign_id)
    
    return {"message": "Campaign resumed successfully"}


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
    Soft delete a campaign
    """
    campaign = await crud_campaign.get_by_id(db=db, campaign_id=campaign_id)
    if campaign is None:
        raise NotFoundException("Campaign not found")
    
    if campaign.user_id != current_user["id"] and not current_user.get("is_superuser"):
        raise ForbiddenException("Not authorized to access this campaign")
    
    success = await crud_campaign.delete(db=db, campaign_id=campaign_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete campaign")
    
    return {"message": "Campaign deleted successfully"}


@router.get("/campaign/limits", response_model=CampaignLimitsResponse)
async def get_campaign_limits(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[dict, Depends(get_current_user)]
) -> CampaignLimitsResponse:
    """
    Get user's campaign limits based on their tier
    """
    subscription_service = SubscriptionService(db)
    limits = await subscription_service.get_user_limits(current_user["id"])
    return CampaignLimitsResponse(**limits)


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
    """Background task to execute campaign processing"""
    from ...core.db.database import async_get_db
    async for session in async_get_db():
        try:
            service = PRKPIService(session, campaign_id)
            await service.execute_campaign()
        except Exception as e:
            print(f"Background campaign execution failed: {e}")
        break


async def resume_campaign_background(campaign_id: int):
    """Background task to resume campaign processing"""
    from ...core.db.database import async_get_db
    async for session in async_get_db():
        try:
            service = PRKPIService(session, campaign_id)
            # You might want to implement resume logic in the service
            await service.execute_campaign()  # For now, restart the campaign
        except Exception as e:
            print(f"Background campaign resumption failed: {e}")
        break


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