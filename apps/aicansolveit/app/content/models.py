from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ContentStatus(str, Enum):  # noqa: UP042
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    scheduled = "scheduled"
    published = "published"
    failed = "failed"


class Language(str, Enum):  # noqa: UP042
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
    body_tr: str  # primary body in Turkish
    asset_ids: list[str]
    scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContentTranslation(BaseModel):
    id: str
    draft_id: str
    language: Language
    body: str
    translated_at: datetime


class ReviewAction(BaseModel):
    feedback: str | None = None  # operator notes for rejected drafts
