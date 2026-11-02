from fastapi import APIRouter, Depends
from app.auth.dependencies import verify_cron_secret
from app.jobs import tasks

router = APIRouter()


@router.post("/generate", dependencies=[Depends(verify_cron_secret)])
async def trigger_generation_all():
    """
    Railway cron endpoint — triggers content generation for all active hotels.
    Called weekly via Railway cron: POST /internal/jobs/generate
    Header: X-Cron-Secret: <cron_secret>
    """
    tasks.generate_all_hotels_task.delay()
    return {"status": "queued"}


@router.post("/generate/{hotel_id}", dependencies=[Depends(verify_cron_secret)])
async def trigger_generation_hotel(hotel_id: str):
    """
    Manually trigger content generation for a single hotel.
    Useful for operator dashboard one-off runs.
    """
    tasks.generate_content_task.delay(hotel_id)
    return {"status": "queued", "hotel_id": hotel_id}
