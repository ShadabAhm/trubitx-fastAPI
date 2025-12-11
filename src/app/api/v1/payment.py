from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, UTC, timedelta
import razorpay, hmac, hashlib
import logging

from ...core.db.database import async_get_db
from ...models.payment import Payment
from ...models.user import User
from ...models.tier import Tier
from ...models.user_subscription import UserSubscription
from ..dependencies import get_current_user
from ...core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["Payment"])


# Initialize Razorpay client using environment variables
razor_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)

# -------------------------
# Create Order
# -------------------------
class CreateOrderRequest(BaseModel):
    amount: float
    plan_name: str


@router.post("/create-order")
async def create_order(
    data: CreateOrderRequest,
    db: AsyncSession = Depends(async_get_db),
    current_user=Depends(get_current_user),
):
    try:
        # Find the tier by plan name
        tier_result = await db.execute(select(Tier).where(Tier.name == data.plan_name))
        tier = tier_result.scalar_one_or_none()

        if not tier:
            raise HTTPException(status_code=404, detail=f"Plan '{data.plan_name}' not found")

        # Handle free plan separately
        if data.amount == 0:
            # Create unique order_id for free plan
            free_order_id = f"free_plan_{current_user['id']}_{int(datetime.now(UTC).timestamp())}"

            payment = Payment(
                user_id=current_user["id"],
                plan_name=data.plan_name,
                amount=data.amount,
                order_id=free_order_id,
                status="free",
            )
            db.add(payment)

            # Assign tier to user
            await db.execute(
                update(User)
                .where(User.id == current_user["id"])
                .values(tier_id=tier.id, updated_at=datetime.now(UTC))
            )

            # Create subscription record
            subscription = UserSubscription(
                user_id=current_user["id"],
                tier_id=tier.id,
                is_active=True,
                start_date=datetime.now(UTC),
                end_date=datetime.now(UTC) + timedelta(days=14),  # Free plan: 14 days
            )
            db.add(subscription)

            await db.commit()
            await db.refresh(payment)

            return {
                "message": "Free plan activated successfully",
                "status": "free",
                "tier_id": tier.id,
                "tier_name": tier.name
            }

        # Create Razorpay order for paid plans
        order = razor_client.order.create({
            "amount": int(data.amount * 100),
            "currency": "INR",
            "payment_capture": 1
        })

        payment = Payment(
            user_id=current_user["id"],
            plan_name=data.plan_name,
            amount=data.amount,
            order_id=order["id"],
            status="pending",
        )
        db.add(payment)
        await db.commit()
        await db.refresh(payment)

        return {"order_id": order["id"], "key": settings.RAZORPAY_KEY_ID}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------
# Verify Payment
# -------------------------
class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/verify-payment")
async def verify_payment(
    data: VerifyPaymentRequest,
    db: AsyncSession = Depends(async_get_db)
):
    try:
        # Generate signature
        payload = f"{data.razorpay_order_id}|{data.razorpay_payment_id}"
        generated_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

        # Fetch payment record
        result = await db.execute(select(Payment).filter(Payment.order_id == data.razorpay_order_id))
        payment = result.scalars().first()

        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        if generated_signature == data.razorpay_signature:
            payment.payment_id = data.razorpay_payment_id
            payment.status = "verified"
            payment.updated_at = datetime.now(UTC)

            # Find the tier by plan name
            tier_result = await db.execute(select(Tier).where(Tier.name == payment.plan_name))
            tier = tier_result.scalar_one_or_none()

            if not tier:
                logger.error(f"Tier not found for plan: {payment.plan_name}")
                raise HTTPException(status_code=404, detail=f"Plan '{payment.plan_name}' not found")

            # Assign tier to user
            await db.execute(
                update(User)
                .where(User.id == payment.user_id)
                .values(tier_id=tier.id, updated_at=datetime.now(UTC))
            )

            # Calculate subscription duration based on tier
            if "Annual" in tier.name or "annual" in tier.name.lower():
                duration_days = 365
            elif "Monthly" in tier.name or "monthly" in tier.name.lower():
                duration_days = 30
            else:
                duration_days = 30  # Default to monthly

            # Deactivate any existing active subscriptions for this user
            await db.execute(
                update(UserSubscription)
                .where(UserSubscription.user_id == payment.user_id)
                .where(UserSubscription.is_active == True)
                .values(is_active=False, updated_at=datetime.now(UTC))
            )

            # Create new subscription record
            subscription = UserSubscription(
                user_id=payment.user_id,
                tier_id=tier.id,
                is_active=True,
                start_date=datetime.now(UTC),
                end_date=datetime.now(UTC) + timedelta(days=duration_days),
            )
            db.add(subscription)

            await db.commit()

            return {
                "status": "success",
                "message": "Payment verified successfully",
                "tier_id": tier.id,
                "tier_name": tier.name
            }
        else:
            payment.status = "failed"
            await db.commit()
            raise HTTPException(status_code=400, detail="Invalid signature")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
