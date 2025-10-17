from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.security import create_access_token, decode_access_token, get_password_hash, TokenType
from ...crud.crud_users import crud_users
import smtplib
from email.mime.text import MIMEText

router = APIRouter(tags=["Forgot Password"])

# --- Request schemas ---
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# --- Placeholder for sending email ---
async def send_password_reset_email(email: str, token: str):
    reset_link = f"https://yourfrontend.com/reset-password?token={token}"
    print(f"[DEBUG] Send password reset email to {email} with link: {reset_link}")
    # TODO: Replace print with real email sending


# --- Forgot Password Endpoint ---
@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)]
):
    user = await crud_users.get(db=db, email=request.email)

    if user:
        token_expires = timedelta(hours=1)
        token = await create_access_token(
            data={"sub": user["email"], "type": TokenType.PASSWORD_RESET},
            expires_delta=token_expires
        )
        await send_password_reset_email(user["email"], token)

    # Security: always return the same message
    return {"message": "If this email exists, a reset link has been sent"}


# --- Reset Password Endpoint ---
@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)]
):
    try:
        payload = decode_access_token(request.token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    # Check token type
    if payload.get("type") != TokenType.PASSWORD_RESET:
        raise HTTPException(status_code=400, detail="Invalid token type")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    user = await crud_users.get(db=db, email=email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update password
    hashed_password = get_password_hash(request.new_password)
    await crud_users.update(db=db, object={"hashed_password": hashed_password}, username=user.username)

    return {"message": "Password has been successfully reset"}
