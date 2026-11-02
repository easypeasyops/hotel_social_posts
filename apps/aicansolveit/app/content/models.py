from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class ContentStatus(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    scheduled = "scheduled"
    published = "published"
    failed = "failed"


class Language(str, Enum):
    tr = "tr"
    en = "en"
    de = "de"
    ru = "ru"
    ar = "ar"


class ContentDraft(BaseModel):
    id: str
    hotel_id: str
    channel: str
    status: ContentStatus
    body_tr: str                       # primary body in Turkish
    asset_ids: list[str]
    scheduled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ContentTranslation(BaseModel):
    id: str
    draft_id: str
    language: Language
    body: str
    translated_at: datetime


class ReviewAction(BaseModel):
    feedback: Optional[str] = None    # operator notes for rejected drafts
