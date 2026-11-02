from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


class SubscriptionTier(str, Enum):
    standard = "standard"    # $299/mo — TR + EN
    growth = "growth"        # $599/mo — TR + EN + DE + RU + AR
    premium = "premium"      # $899/mo — growth + priority generation


class SocialChannel(str, Enum):
    instagram = "instagram"
    facebook = "facebook"
    tiktok = "tiktok"
    google_business = "google_business"


class HotelCreate(BaseModel):
    name: str
    slug: str = Field(..., pattern=r"^[a-z0-9-]+$", description="URL-safe identifier")
    location: str
    description: Optional[str] = None
    tier: SubscriptionTier = SubscriptionTier.standard
    channels: list[SocialChannel] = [SocialChannel.instagram, SocialChannel.facebook]
    contact_email: str


class HotelUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tier: Optional[SubscriptionTier] = None
    channels: Optional[list[SocialChannel]] = None
    contact_email: Optional[str] = None


class Hotel(BaseModel):
    id: str
    name: str
    slug: str
    location: str
    description: Optional[str]
    tier: SubscriptionTier
    channels: list[SocialChannel]
    contact_email: str
    created_at: datetime
    updated_at: datetime
