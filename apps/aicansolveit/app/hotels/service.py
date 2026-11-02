from supabase import Client
from app.hotels.models import HotelCreate, HotelUpdate
from fastapi import HTTPException


def list_hotels(db: Client) -> list[dict]:
    response = db.table("hotels").select("*").order("created_at", desc=True).execute()
    return response.data


def get_hotel(db: Client, hotel_id: str) -> dict:
    response = db.table("hotels").select("*").eq("id", hotel_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return response.data


def get_hotel_by_slug(db: Client, slug: str) -> dict:
    response = db.table("hotels").select("*").eq("slug", slug).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return response.data


def create_hotel(db: Client, payload: HotelCreate) -> dict:
    data = payload.model_dump()
    data["channels"] = [c.value for c in payload.channels]
    response = db.table("hotels").insert(data).execute()
    return response.data[0]


def update_hotel(db: Client, hotel_id: str, payload: HotelUpdate) -> dict:
    data = payload.model_dump(exclude_none=True)
    if "channels" in data:
        data["channels"] = [c.value for c in payload.channels]
    response = db.table("hotels").update(data).eq("id", hotel_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Hotel not found")
    return response.data[0]


def delete_hotel(db: Client, hotel_id: str) -> None:
    db.table("hotels").delete().eq("id", hotel_id).execute()
