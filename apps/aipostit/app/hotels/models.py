from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SubscriptionTier(str, Enum):  # noqa: UP042
    standard = "standard"  # $299/mo — TR + EN
    growth = "growth"  # $599/mo — TR + EN + DE + RU + AR
    premium = "premium"  # $899/mo — growth + priority generation


class SocialChannel(str, Enum):  # noqa: UP042
    instagram = "instagram"
    facebook = "facebook"
    tiktok = "tiktok"
    google_business = "google_business"


class HotelCreate(BaseModel):
    name: str
    slug: str = Field(..., pattern=r"^[a-z0-9-]+$", description="URL-safe identifier")
    location: str
    description: str | None = None
    tier: SubscriptionTier = SubscriptionTier.standard
    channels: list[SocialChannel] = [SocialChannel.instagram, SocialChannel.facebook]
    contact_email: str


class HotelUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    description: str | None = None
    tier: SubscriptionTier | None = None
    channels: list[SocialChannel] | None = None
    contact_email: str | None = None
    # Days an ended invite's row, and so its email, is kept (migration 006; purge_ended_invites).
    invite_retention_days: int | None = Field(None, ge=7, le=180)


class Hotel(BaseModel):
    id: str
    name: str
    slug: str
    location: str
    description: str | None
    tier: SubscriptionTier
    channels: list[SocialChannel]
    contact_email: str
    created_at: datetime
    updated_at: datetime
