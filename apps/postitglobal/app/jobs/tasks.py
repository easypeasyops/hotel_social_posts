from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.config import get_settings
from app.observability import configure_logging

settings = get_settings()
celery_app = Celery("postitglobal", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Istanbul",
    enable_utc=True,
)


@setup_logging.connect
def _json_logs(**_: Any) -> None:
    """The worker logs JSON on stdout like the API (Celery otherwise installs its own)."""
    configure_logging(settings.log_level, json_output=settings.log_json)


@celery_app.task(name="tasks.process_asset", bind=True, max_retries=3)
def process_asset_task(self, asset_id: str):
    """
    Processes an uploaded asset: validates file, updates status to 'ready'.
    Future: resize images, extract metadata, move large files to R2.
    """
    from app.database import get_supabase

    db = get_supabase()

    try:
        db.table("assets").update({"status": "ready"}).eq("id", asset_id).execute()
    except Exception as exc:
        db.table("assets").update({"status": "failed"}).eq("id", asset_id).execute()
        raise self.retry(exc=exc, countdown=60)  # noqa: B904


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
