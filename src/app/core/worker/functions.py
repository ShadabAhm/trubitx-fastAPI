import asyncio
import logging
from datetime import datetime, UTC

import uvloop
from arq.worker import Worker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from ...core.config import settings
from ...models.pr_campaign import Campaign
from ...services.pr_kpi_service import PRKPIService

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)


# -------- background tasks --------
async def sample_background_task(ctx: Worker, name: str) -> str:
    await asyncio.sleep(5)
    return f"Task {name} is complete!"


async def check_and_run_recurring_campaigns(ctx: Worker) -> str:
    """
    Periodic task to check and execute recurring campaigns.
    Runs every hour to check if any recurring campaigns need to be executed.
    """
    logger.info("Checking for recurring campaigns to execute...")

    # Create database session
    engine = create_async_engine(
        f"{settings.POSTGRES_ASYNC_PREFIX}{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}",
        echo=False
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        try:
            # Find campaigns that need to run
            now = datetime.now(UTC)
            result = await db.execute(
                select(Campaign).where(
                    Campaign.is_recurring == True,
                    Campaign.status == 'active',
                    Campaign.next_run_at <= now
                )
            )
            campaigns_to_run = result.scalars().all()

            logger.info(f"Found {len(campaigns_to_run)} recurring campaigns to execute")

            for campaign in campaigns_to_run:
                try:
                    logger.info(f"Executing recurring campaign {campaign.id}: {campaign.name}")

                    # Execute campaign
                    service = PRKPIService(db, campaign.id)
                    success = await service.execute_campaign()

                    if success:
                        logger.info(f"Successfully executed recurring campaign {campaign.id}")
                    else:
                        logger.error(f"Failed to execute recurring campaign {campaign.id}")

                except Exception as e:
                    logger.error(f"Error executing recurring campaign {campaign.id}: {e}")
                    continue

            return f"Processed {len(campaigns_to_run)} recurring campaigns"

        except Exception as e:
            logger.error(f"Error in check_and_run_recurring_campaigns: {e}")
            return f"Error: {str(e)}"
        finally:
            await engine.dispose()


# -------- base functions --------
async def startup(ctx: Worker) -> None:
    logging.info("Worker Started")


async def shutdown(ctx: Worker) -> None:
    logging.info("Worker end")
