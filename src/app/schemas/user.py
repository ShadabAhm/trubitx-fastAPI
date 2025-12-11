from datetime import datetime
from typing import Annotated, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


# ✅ Common base for all users
class UserBase(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=30, examples=["John Doe"])]
    username: Annotated[str, Field(min_length=2, max_length=20, pattern=r"^[a-z0-9]+$", examples=["johndoe"])]
    email: Annotated[EmailStr, Field(examples=["john.doe@example.com"])]
    phone_number: Annotated[Optional[str], Field(pattern=r"^\+?[0-9]{7,15}$", default=None, examples=["+919876543210"])]


# ✅ Complete internal user model (database)
class User(TimestampSchema, UserBase, UUIDSchema, PersistentDeletion):
    profile_image_url: Annotated[str, Field(default="https://www.profileimageurl.com")]
    hashed_password: str
    is_superuser: bool = False
    role: Annotated[str, Field(default="user", examples=["user", "admin"])]
    tier_id: Optional[int] = None


# ✅ What we send back to frontend
class UserRead(BaseModel):
    id: int
    name: str
    username: str
    email: EmailStr
    phone_number: Optional[str] = None
    company_name: Optional[str] = None
    profile_image_url: str
    role: str
    tier_id: Optional[int] = None
    tier_name: Optional[str] = None  # Tier name for display
    tier_duration: Optional[str] = None  # Tier duration for display


# ✅ Used during registration
class UserCreate(UserBase):
    model_config = ConfigDict(extra="forbid")
    
    password: str = Field(examples=["StrongP@ss1"])
    company_name: Optional[str] = Field(default=None, examples=["Acme Corp"])
    terms_accepted: bool = Field(default=False, examples=[True])

    @model_validator(mode="before")
    def check_password(cls, values):
        password = values.get("password")
        if password is None:
            return values
        # check length
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        # check at least one uppercase
        if not any(c.isupper() for c in password):
            raise ValueError("Password must have at least one uppercase letter")
        # check at least one lowercase
        if not any(c.islower() for c in password):
            raise ValueError("Password must have at least one lowercase letter")
        # check at least one digit
        if not any(c.isdigit() for c in password):
            raise ValueError("Password must have at least one digit")
        # check at least one special char
        if not any(c in "@$!%*?&" for c in password):
            raise ValueError("Password must have at least one special character @$!%*?&")
        return values


# ✅ Internal version (stores hashed password)
class UserCreateInternal(UserBase):
    hashed_password: str
    company_name: Optional[str] = None


# ✅ Update profile fields
class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    profile_image_url: Optional[str] = None


class UserUpdateInternal(UserUpdate):
    updated_at: datetime


class UserTierUpdate(BaseModel):
    tier_id: int


class UserDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_deleted: bool
    deleted_at: datetime


class UserRestoreDeleted(BaseModel):
    is_deleted: bool
