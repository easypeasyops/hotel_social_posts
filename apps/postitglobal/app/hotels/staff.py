"""Hotel staff: Supabase accounts tied to one hotel (table hotel_members)."""

from typing import cast

from supabase import Client


def hotel_of(db: Client, user_id: str) -> str | None:
    """The hotel this account works for, or None if it isn't hotel staff."""
    response = db.table("hotel_members").select("hotel_id").eq("user_id", user_id).execute()
    rows = cast(list[dict], response.data)
    return rows[0]["hotel_id"] if rows else None


def list_members(db: Client, hotel_id: str) -> list[dict]:
    response = (
        db.table("hotel_members")
        .select("user_id, email, created_at")
        .eq("hotel_id", hotel_id)
        .order("created_at")
        .execute()
    )
    return cast(list[dict], response.data)


def remove_member(db: Client, hotel_id: str, user_id: str) -> None:
    """Take a staff account's access to this hotel away. The Supabase account stays, with no
    access; its open session gets 403 on its next request."""
    db.table("hotel_members").delete().eq("hotel_id", hotel_id).eq("user_id", user_id).execute()
