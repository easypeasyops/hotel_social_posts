"""Hotel staff: Supabase accounts tied to one hotel (table hotel_members)."""

from typing import cast

from supabase import Client


def hotel_of(db: Client, user_id: str) -> str | None:
    """The hotel this account works for, or None if it isn't hotel staff."""
    response = db.table("hotel_members").select("hotel_id").eq("user_id", user_id).execute()
    rows = cast(list[dict], response.data)
    return rows[0]["hotel_id"] if rows else None
