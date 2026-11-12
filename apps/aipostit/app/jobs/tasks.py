import logging
import time
from typing import Any

from celery import Celery
from celery.signals import before_task_publish, celeryd_init, setup_logging

from app.config import get_settings
from app.jobs.queue_metrics import PUBLISHED_AT_HEADER
from app.observability import configure_logging, init_error_tracking

log = logging.getLogger(__name__)
settings = get_settings()
celery_app = Celery("aipostit", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Istanbul",
    enable_utc=True,
)


@celeryd_init.connect
def _error_tracking(**_: Any) -> None:
    """The worker reports its tasks' errors like the API. In the main process, before it
    forks: each child inherits the setup and starts its own sending thread when first used."""
    init_error_tracking(
        settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release,
    )


@setup_logging.connect
def _json_logs(**_: Any) -> None:
    """The worker logs JSON on stdout like the API (Celery otherwise installs its own)."""
    configure_logging(settings.log_level, json_output=settings.log_json)


@before_task_publish.connect
def _stamp_publish_time(headers: dict[str, Any], **_: Any) -> None:
    """Every queued task says when it was queued, for the queue's age metric."""
    headers[PUBLISHED_AT_HEADER] = time.time()


@celery_app.task(name="tasks.process_asset", bind=True, max_retries=3)
def process_asset_task(self, asset_id: str):
    """
    Processes an uploaded asset: makes a photo's thumbnail (app/assets/thumbnails.py), then
    marks the asset 'ready'. A photo that won't open is 'failed' without a retry, since
    retrying can't mend the file. Other files (videos) are ready as they are.
    """
    from PIL import Image

    from app.assets.service import STORAGE_BUCKET
    from app.assets.thumbnails import make_thumbnail, thumbnail_path
    from app.database import get_supabase
    from app.publishing.buffer import IMAGE_TYPES, image_suffix

    db = get_supabase()

    try:
        rows = db.table("assets").select("*").eq("id", asset_id).execute().data
        if not rows:
            return  # deleted before the worker got to it
        asset, update = rows[0], {"status": "ready"}
        if image_suffix(asset) in IMAGE_TYPES:
            bucket = db.storage.from_(STORAGE_BUCKET)
            try:
                thumbnail = make_thumbnail(bucket.download(asset["storage_path"]))
            except (OSError, Image.DecompressionBombError) as exc:
                log.warning("Asset %s is not a photo Pillow can open: %s", asset_id, exc)
                db.table("assets").update({"status": "failed"}).eq("id", asset_id).execute()
                return
            path = thumbnail_path(asset)
            bucket.upload(path, thumbnail, {"content-type": "image/webp", "upsert": "true"})
            update["thumbnail_path"] = path
        db.table("assets").update(update).eq("id", asset_id).execute()
    except Exception as exc:
        db.table("assets").update({"status": "failed"}).eq("id", asset_id).execute()
        raise self.retry(exc=exc, countdown=60)  # noqa: B904


@celery_app.task(name="tasks.backfill_thumbnails")
def backfill_thumbnails_task() -> int:
    """
    Makes the thumbnails photos uploaded before thumbnails existed (0.3.7) don't have yet, and
    returns how many it made. Run it by hand (RUNBOOK); running it again only does what's left.
    A photo that won't open, or a storage error, is logged and skipped: the photo stays ready,
    and the pages keep showing it full size.
    """
    from PIL import Image

    from app.assets.service import STORAGE_BUCKET
    from app.assets.thumbnails import make_thumbnail, thumbnail_path
    from app.database import get_supabase
    from app.publishing.buffer import IMAGE_TYPES, image_suffix

    db = get_supabase()
    bucket = db.storage.from_(STORAGE_BUCKET)
    rows = db.table("assets").select("*").eq("status", "ready").execute().data
    made = 0
    for asset in rows:
        if asset.get("thumbnail_path") or image_suffix(asset) not in IMAGE_TYPES:
            continue
        try:
            thumbnail = make_thumbnail(bucket.download(asset["storage_path"]))
            path = thumbnail_path(asset)
            bucket.upload(path, thumbnail, {"content-type": "image/webp", "upsert": "true"})
            db.table("assets").update({"thumbnail_path": path}).eq("id", asset["id"]).execute()
            made += 1
        except (OSError, Image.DecompressionBombError) as exc:
            log.warning("Asset %s is not a photo Pillow can open: %s", asset["id"], exc)
        except Exception:
            log.exception("Could not make a thumbnail for asset %s", asset["id"])
    log.info("Made %d thumbnails", made)
    return made


@celery_app.task(name="tasks.generate_all_hotels")
def generate_all_hotels_task():
    """
    Fetches all active hotels and enqueues individual generation tasks.
    Queued weekly by the cluster's generate-weekly CronJob (celery call), or by
    POST /internal/jobs/generate.
    """
    from app.database import get_supabase

    db = get_supabase()

    hotels = db.table("hotels").select("id").execute().data
    for hotel in hotels:
        generate_content_task.delay(hotel["id"])


@celery_app.task(name="tasks.generate_content", bind=True, max_retries=2)
def generate_content_task(self, hotel_id: str):
    """
    Generates content drafts for a single hotel using Claude API,
    then enqueues translation for each draft.
    """
    from app.database import get_supabase
    from app.generation.claude import generate_drafts_for_hotel

    db = get_supabase()
    try:
        draft_ids = generate_drafts_for_hotel(db, hotel_id)
        for draft_id in draft_ids:
            translate_content_task.delay(draft_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=120)  # noqa: B904


@celery_app.task(name="tasks.translate_content", bind=True, max_retries=3)
def translate_content_task(self, draft_id: str):
    """
    Translates a draft into all languages enabled for the hotel tier.
    Runs parallel DeepL calls via asyncio within the task.
    """
    import asyncio

    from app.database import get_supabase
    from app.translation.deepl import translate_draft

    db = get_supabase()
    try:
        asyncio.run(translate_draft(db, draft_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)  # noqa: B904


@celery_app.task(name="tasks.publish_content", bind=True, max_retries=3)
def publish_content_task(self, draft_id: str):
    """
    Publishes an approved draft to Buffer for scheduling.
    Updates draft status to 'scheduled' on success.
    """
    from app.database import get_supabase
    from app.publishing.buffer import publish_draft

    db = get_supabase()
    try:
        publish_draft(db, draft_id)
        db.table("content_drafts").update({"status": "scheduled"}).eq("id", draft_id).execute()
    except Exception as exc:
        db.table("content_drafts").update({"status": "failed"}).eq("id", draft_id).execute()
        raise self.retry(exc=exc, countdown=60)  # noqa: B904


@celery_app.task(name="tasks.sync_buffer_posts")
def sync_buffer_posts_task():
    """
    Marks each draft Buffer has sent as published, and each it couldn't send as failed.
    Queued hourly by the cluster's sync-buffer CronJob (celery call).
    """
    from app.database import get_supabase
    from app.publishing.buffer import sync_scheduled_posts

    sync_scheduled_posts(get_supabase())


@celery_app.task(name="tasks.purge_ended_invites")
def purge_ended_invites_task() -> int:
    """Deletes staff invites that ended longer ago than their hotel keeps them. No retries:
    the deletes are idempotent and the next run catches up. Not scheduled yet (spec PR 8)."""
    from app.database import get_supabase
    from app.hotels.invites import purge_ended_invites

    return purge_ended_invites(get_supabase())
