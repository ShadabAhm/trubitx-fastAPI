from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import razorpay, hmac, hashlib

from ...core.db.database import async_get_db
from ...models.payment import Payment
from ..dependencies import get_current_user

router = APIRouter(prefix="/payment", tags=["Payment"])

RAZORPAY_KEY_ID = "rzp_test_Rbc8mXXdwuWUOS"
RAZORPAY_KEY_SECRET = "rvsE94QNaiDh4ttPHtUuyb4y"

razor_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


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
        # Handle free plan separately
        if data.amount == 0:
            payment = Payment(
                user_id=current_user["id"],
                plan_name=data.plan_name,
                amount=data.amount,
                order_id="free_plan",
                status="free",
            )
            db.add(payment)
            await db.commit()
            await db.refresh(payment)
            return {"message": "Free plan activated successfully", "status": "free"}

        # Otherwise, create Razorpay order
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

        return {"order_id": order["id"], "key": RAZORPAY_KEY_ID}

    except Exception as e:
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
            RAZORPAY_KEY_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

        # Get payment record
        result = await db.execute(select(Payment).filter(Payment.order_id == data.razorpay_order_id))
        payment = result.scalars().first()

        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        if generated_signature == data.razorpay_signature:
            payment.payment_id = data.razorpay_payment_id
            payment.status = "verified"
            payment.updated_at = datetime.utcnow()
            await db.commit()
            return {"status": "success", "message": "Payment verified successfully"}
        else:
            payment.status = "failed"
            await db.commit()
            raise HTTPException(status_code=400, detail="Invalid signature")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
