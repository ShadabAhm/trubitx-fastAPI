from datetime import timedelta
from typing import Annotated
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.security import create_access_token, decode_access_token, get_password_hash, TokenType
from ...crud.crud_users import crud_users
from ...core.config import settings

router = APIRouter(tags=["Forgot Password"])

SMTP_SERVER = settings.SMTP_SERVER
SMTP_PORT = settings.SMTP_PORT
SMTP_USERNAME = settings.SMTP_USERNAME
SMTP_PASSWORD = settings.SMTP_PASSWORD
FROM_EMAIL = settings.FROM_EMAIL or settings.SMTP_USERNAME
FRONTEND_URL = settings.FRONTEND_URL

# --- Request Schemas ---
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# --- Email Sending Function ---
async def send_password_reset_email(email: str, token: str):
    """
    Send password reset email using SMTP credentials from environment.
    """
    try:
        reset_link = f"{FRONTEND_URL}/reset-password?token={token}"
        subject = "Password Reset Request"

        # HTML email
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Password Reset Request</h2>
            <p>Hello,</p>
            <p>You requested a password reset. Click below to reset your password:</p>
            <p><a href="{reset_link}" style="background: #3b82f6; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Reset Password</a></p>
            <p>If this link doesn't work, copy and paste this in your browser:</p>
            <p>{reset_link}</p>
            <p><strong>This link will expire in 1 hour.</strong></p>
            <p>If you didn't request a reset, please ignore this email.</p>
        </body>
        </html>
        """

        text_content = f"""
        Password Reset Request

        Hello,
        You requested a password reset. Use the link below to create a new password:
        {reset_link}

        This link will expire in 1 hour.
        If you didn't request this reset, please ignore this email.
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = FROM_EMAIL
        msg['To'] = email
        msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"Password reset email sent to {email}")

    except smtplib.SMTPAuthenticationError:
        print("SMTP authentication failed. Check your Gmail App Password and username.")
    except smtplib.SMTPException as e:
        print(f"SMTP error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")


# --- Forgot Password Endpoint ---
@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(async_get_db)]
):
    user = await crud_users.get(db=db, email=request.email)

    if user:
        token_expires = timedelta(hours=1)
        token = await create_access_token(
            data={"sub": user["email"], "type": TokenType.PASSWORD_RESET},
            expires_delta=token_expires,
        )
        background_tasks.add_task(send_password_reset_email, user["email"], token)

    return {"message": "If this email exists, a reset link has been sent"}


# --- Reset Password Endpoint ---
@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)]
):
    try:
        payload = await decode_access_token(request.token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if payload.get("type") != TokenType.PASSWORD_RESET:
        raise HTTPException(status_code=400, detail="Invalid token type")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    user = await crud_users.get(db=db, email=email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    hashed_password = get_password_hash(request.new_password)
    await crud_users.update(db=db, object={"hashed_password": hashed_password}, username=user["username"])

    return {"message": "Password has been successfully reset"}
