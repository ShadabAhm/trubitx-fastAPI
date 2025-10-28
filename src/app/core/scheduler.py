from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.future import select

from app.core.db.database import async_get_db
from app.models.pr_campaign import Campaign

scheduler = AsyncIOScheduler()


# Fetch and execute all due recurring campaigns
async def fetch_and_run_due_campaigns():
    print("Checking for due recurring campaigns...")

    # Lazy import here to avoid circular import
    from app.api.v1.campaigns import execute_campaign_background

    async for session in async_get_db():
        try:
            result = await session.execute(
                select(Campaign).where(
                    Campaign.is_recurring == True,
                    Campaign.status == "active",
                    Campaign.next_run_at <= datetime.now(timezone.utc),
                )
            )
            due_campaigns = result.scalars().all()

            if not due_campaigns:
                print("No due recurring campaigns found.")
                return

            for campaign in due_campaigns:
                print(f"Running recurring campaign: {campaign.name} (ID: {campaign.id})")

                await execute_campaign_background(campaign.id)

                campaign.last_run_at = datetime.now(timezone.utc)
                campaign.next_run_at = datetime.now(timezone.utc) + timedelta(
                    hours=campaign.interval_hours or 24
                )
                session.add(campaign)

            await session.commit()
            print(f"{len(due_campaigns)} recurring campaigns executed successfully.")

        except Exception as e:
            print(f"Error while executing recurring campaigns: {e}")
        finally:
            break


# Pause/resume campaign jobs dynamically
def pause_campaign_job(campaign_id: int):
    job_id = f"campaign_{campaign_id}"
    job = scheduler.get_job(job_id)
    if job:
        job.pause()
        print(f"Paused scheduler job for Campaign ID: {campaign_id}")
    else:
        print(f"No active job found for Campaign ID: {campaign_id}")


def resume_campaign_job(campaign_id: int, interval_hours: int = 24):
    # Lazy import to avoid circular import
    from app.api.v1.campaigns import execute_campaign_background

    job_id = f"campaign_{campaign_id}"
    job = scheduler.get_job(job_id)

    if job:
        job.resume()
        print(f"Resumed scheduler job for Campaign ID: {campaign_id}")
    else:
        # Recreate job if missing
        scheduler.add_job(
            execute_campaign_background,
            trigger=IntervalTrigger(hours=interval_hours),
            args=[campaign_id],
            id=job_id,
            replace_existing=True,
        )
        print(f"Created & started new scheduler job for Campaign ID: {campaign_id}")


# Start the global scheduler
def start_scheduler():
    try:
        scheduler.add_job(
            fetch_and_run_due_campaigns,
            trigger=IntervalTrigger(hours=1),
            id="recurring_campaign_checker",
            replace_existing=True,
        )
        scheduler.start()
        print("Campaign Scheduler Started (runs every 1 hour).")
    except Exception as e:
        print(f"Failed to start scheduler: {e}")
