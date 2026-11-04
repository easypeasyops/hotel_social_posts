from fastapi import APIRouter, Depends

from app.auth.dependencies import verify_cron_secret
from app.jobs import tasks

router = APIRouter()


@router.post("/generate", dependencies=[Depends(verify_cron_secret)])
def trigger_generation_all():
    """
    Triggers content generation for all active hotels, by hand: POST /internal/jobs/generate
    with the X-Cron-Secret header. The weekly run is the cluster's CronJob
    (deploy/service/values.yaml, generate-weekly), which queues the task directly.
    """
    tasks.generate_all_hotels_task.delay()
    return {"status": "queued"}


@router.post("/generate/{hotel_id}", dependencies=[Depends(verify_cron_secret)])
def trigger_generation_hotel(hotel_id: str):
    """
    Manually trigger content generation for a single hotel.
    Useful for operator dashboard one-off runs.
    """
    tasks.generate_content_task.delay(hotel_id)
    return {"status": "queued", "hotel_id": hotel_id}
