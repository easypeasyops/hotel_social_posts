from fastapi import APIRouter, Depends

from app.auth.dependencies import require_operator
from app.database import get_supabase
from app.hotels import service
from app.hotels.models import HotelCreate, HotelUpdate
from supabase import Client

router = APIRouter()


@router.get("")
def list_hotels(
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.list_hotels(db)


@router.post("", status_code=201)
def create_hotel(
    payload: HotelCreate,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.create_hotel(db, payload)


@router.get("/{hotel_id}")
def get_hotel(
    hotel_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.get_hotel(db, hotel_id)


@router.patch("/{hotel_id}")
def update_hotel(
    hotel_id: str,
    payload: HotelUpdate,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.update_hotel(db, hotel_id, payload)


@router.delete("/{hotel_id}", status_code=204)
def delete_hotel(
    hotel_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    service.delete_hotel(db, hotel_id)
