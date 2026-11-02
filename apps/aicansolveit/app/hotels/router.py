from fastapi import APIRouter, Depends
from supabase import Client
from app.database import get_supabase
from app.auth.dependencies import get_current_user
from app.hotels import service
from app.hotels.models import HotelCreate, HotelUpdate

router = APIRouter()


@router.get("")
async def list_hotels(
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.list_hotels(db)


@router.post("", status_code=201)
async def create_hotel(
    payload: HotelCreate,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.create_hotel(db, payload)


@router.get("/{hotel_id}")
async def get_hotel(
    hotel_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.get_hotel(db, hotel_id)


@router.patch("/{hotel_id}")
async def update_hotel(
    hotel_id: str,
    payload: HotelUpdate,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.update_hotel(db, hotel_id, payload)


@router.delete("/{hotel_id}", status_code=204)
async def delete_hotel(
    hotel_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    service.delete_hotel(db, hotel_id)
