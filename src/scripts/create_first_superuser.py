import asyncio
import logging
from datetime import datetime, timezone

from ..app.core.config import settings
from ..app.core.db.database import AsyncSession, local_session
from ..app.core.security import get_password_hash
from ..app.models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_first_user(session: AsyncSession) -> None:
    try:
        name = settings.ADMIN_NAME
        email = settings.ADMIN_EMAIL
        username = settings.ADMIN_USERNAME
        hashed_password = get_password_hash(settings.ADMIN_PASSWORD)

        # Check if user exists
        result = await session.execute(
            User.__table__.select().filter_by(email=email)
        )
        user = result.scalar_one_or_none()

        if user is None:
            new_user = User(
                name=name,
                email=email,
                username=username,
                hashed_password=hashed_password,
                is_superuser=True,
                role="admin",  # use the ORM-defined column
            )
            session.add(new_user)
            await session.commit()
            logger.info(f"Admin user {username} created successfully.")
        else:
            logger.info(f"Admin user {username} already exists.")

    except Exception as e:
        logger.error(f"Error creating admin user: {e}")


async def main():
    async with local_session() as session:
        await create_first_user(session)


if __name__ == "__main__":
    asyncio.run(main())
