"""Upload URLs: a pending asset row, then a signed URL the browser uploads to directly."""

from unittest.mock import MagicMock

from app.assets.models import AssetCategory, UploadUrlRequest
from app.assets.service import STORAGE_BUCKET, create_upload_url

# What storage3's create_signed_upload_url returns (storage3.types.SignedUploadURL).
SIGNED = {
    "signed_url": "https://supabase.invalid/storage/v1/object/upload/sign/x?token=t",
    "signedUrl": "https://supabase.invalid/storage/v1/object/upload/sign/x?token=t",
    "token": "t",
    "path": "x",
}


def test_an_upload_url_comes_from_supabase_storage() -> None:
    db = MagicMock()
    db.storage.from_.return_value.create_signed_upload_url.return_value = SIGNED

    response = create_upload_url(
        db,
        "hotel-1",
        UploadUrlRequest(
            filename="pool.jpg", category=AssetCategory.pool, content_type="image/jpeg"
        ),
    )

    assert response.upload_url == SIGNED["signed_url"]
    assert response.storage_path == f"hotel-1/{response.asset_id}/pool.jpg"
    db.storage.from_.assert_called_once_with(STORAGE_BUCKET)
    db.storage.from_.return_value.create_signed_upload_url.assert_called_once_with(
        response.storage_path
    )
    (row,), _ = db.table.return_value.insert.call_args
    assert row["id"] == response.asset_id
    assert row["status"] == "pending"
