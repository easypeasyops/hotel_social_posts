"""Small copies of a hotel's photos, so pages that list them don't load the full-size files.
The worker makes one per photo when it is uploaded (process_asset_task)."""

from io import BytesIO

from PIL import Image, ImageOps

THUMBNAIL_SIZE = 480  # px on the long side: sharp at the pages' largest tile on a 2x screen


def thumbnail_path(asset: dict) -> str:
    """Beside the originals, in a folder of its own: an uploaded file's name can't clash."""
    return f"thumbnails/{asset['hotel_id']}/{asset['id']}.webp"


def make_thumbnail(data: bytes) -> bytes:
    """`data` (a JPEG or PNG) as a WebP at most THUMBNAIL_SIZE on each side, turned upright
    as the photo's EXIF orientation says. Raises OSError for a file that isn't an image."""
    with Image.open(BytesIO(data)) as image:
        image.draft("RGB", (THUMBNAIL_SIZE, THUMBNAIL_SIZE))  # a JPEG decodes at a smaller scale
        upright = ImageOps.exif_transpose(image)
        upright.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        out = BytesIO()
        upright.convert("RGBA" if upright.has_transparency_data else "RGB").save(
            out, "WEBP", quality=80
        )
        return out.getvalue()
