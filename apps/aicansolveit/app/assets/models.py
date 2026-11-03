from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AssetCategory(str, Enum):  # noqa: UP042
    room = "room"
    pool = "pool"
    food = "food"
    exterior = "exterior"
    lobby = "lobby"
    beach = "beach"
    other = "other"


class AssetStatus(str, Enum):  # noqa: UP042
    pending = "pending"  # uploaded, not yet processed
    processing = "processing"
    ready = "ready"  # processed, available for generation
    failed = "failed"


class AssetCreate(BaseModel):
    hotel_id: str
    filename: str
    category: AssetCategory
    storage_path: str  # path within Supabase Storage bucket


class Asset(BaseModel):
    id: str
    hotel_id: str
    filename: str
    category: AssetCategory
    storage_path: str
    storage_url: str | None  # public or signed URL
    status: AssetStatus
    created_at: datetime
    processed_at: datetime | None


class UploadUrlRequest(BaseModel):
    filename: str
    category: AssetCategory
    content_type: str  # e.g. image/jpeg, video/mp4


class UploadUrlResponse(BaseModel):
    upload_url: str  # presigned URL for direct upload
    storage_path: str  # path to record after upload completes
    asset_id: str  # pre-created asset ID to confirm after upload
