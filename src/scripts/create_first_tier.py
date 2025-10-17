import asyncio
import logging
from sqlalchemy import select
from ..app.core.db.database import AsyncSession, local_session
from ..app.models.tier import Tier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_first_tier(session: AsyncSession) -> None:
    from src.app.models.tier import Tier
   
    try:
        tiers_to_create = [
            # Free Plan
            {
                "id": 1,
                "name": "Free",
                "price": "$0",
                "duration": "14 days",
                "description": "Free basic plan to explore features",
                "sub_description": "Perfect for getting started.",
                "features": [
                    "1 campaign",
                    "Daily Batch Update",
                    "Basic Reporting"
                ],
                "button_text": "Start Free Trial",
                "badge": "Free",
                # PR Campaign Limits
                "max_campaigns": 1,
                "max_competitors": 1,
                "max_duration_days": 7,
                "max_articles_per_campaign": 50
            },

            # Monthly Plans
            {
                "id": 2,
                "name": "Pro Monthly",
                "price": "$99",
                "duration": "1 month",
                "description": "Best for growing businesses",
                "sub_description": "Access to all core features with monthly billing.",
                "features": [
                    "50 campaigns",
                    "Advanced Analytics",
                    "Priority Email Support"
                ],
                "button_text": "Subscribe Monthly",
                "badge": "Pro",
                "highlighted": True,
                # PR Campaign Limits
                "max_campaigns": 5,
                "max_competitors": 3,
                "max_duration_days": 14,
                "max_articles_per_campaign": 200
            },
            {
                "id": 3,
                "name": "Enterprise Monthly",
                "price": "$249",
                "duration": "1 month",
                "description": "For teams and enterprises",
                "sub_description": "Unlimited access with dedicated support.",
                "features": [
                    "Unlimited campaigns",
                    "Team Collaboration Tools",
                    "Dedicated Account Manager"
                ],
                "button_text": "Contact Sales",
                "badge": "Enterprise",
                # PR Campaign Limits
                "max_campaigns": 20,
                "max_competitors": 5,
                "max_duration_days": 30,
                "max_articles_per_campaign": 500
            },

            # Annual Plans
            {
                "id": 4,
                "name": "Pro Annual",
                "price": "$79",
                "duration": "12 months",
                "description": "Save 20% with annual billing",
                "sub_description": "Ideal for long-term users who want the best value.",
                "features": [
                    "50 campaigns",
                    "Advanced Analytics",
                    "Priority Email Support"
                ],
                "button_text": "Subscribe Annually",
                "badge": "Pro",
                "highlighted": True,
                # PR Campaign Limits
                "max_campaigns": 5,
                "max_competitors": 3,
                "max_duration_days": 14,
                "max_articles_per_campaign": 200
            },
            {
                "id": 5,
                "name": "Enterprise Annual",
                "price": "$199",
                "duration": "12 months",
                "description": "For large teams — billed annually",
                "sub_description": "Save more with yearly commitment and 24/7 support.",
                "features": [
                    "Unlimited campaigns",
                    "Team Collaboration Tools",
                    "Dedicated Account Manager",
                    "Custom Integrations"
                ],
                "button_text": "Contact Sales",
                "badge": "Enterprise",
                # PR Campaign Limits
                "max_campaigns": 20,
                "max_competitors": 5,
                "max_duration_days": 30,
                "max_articles_per_campaign": 500
            },
        ]

        for tier_data in tiers_to_create:
            query = select(Tier).where(Tier.name == tier_data["name"])
            result = await session.execute(query)
            tier = result.scalar_one_or_none()

            if tier is None:
                session.add(Tier(**tier_data))
                await session.commit()
                logger.info(f"Tier '{tier_data['name']}' created successfully.")
            else:
                # Update existing tier with PR campaign limits
                for key, value in tier_data.items():
                    if hasattr(tier, key):
                        setattr(tier, key, value)
                await session.commit()
                logger.info(f"Tier '{tier_data['name']}' updated with PR campaign limits.")

    except Exception as e:
        logger.error(f"Error creating tiers: {e}")

async def main():
    async with local_session() as session:
        await create_first_tier(session)

if __name__ == "__main__":
    asyncio.run(main())