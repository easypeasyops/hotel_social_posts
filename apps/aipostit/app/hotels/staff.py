"""Hotel staff: Supabase accounts tied to one hotel (table hotel_members)."""

from typing import cast

from supabase import Client

ROLES = ("hotel_admin", "content_moderator", "content_creator")
MODERATORS = ("hotel_admin", "content_moderator")
ROLE_LABELS_TR = {
    "hotel_admin": "Otel yöneticisi",
    "content_moderator": "İçerik moderatörü",
    "content_creator": "İçerik üreticisi",
}


def member_of(db: Client, user_id: str) -> dict | None:
    """This account's hotel and role (hotel_id, role), or None if it isn't hotel staff."""
    response = db.table("hotel_members").select("hotel_id, role").eq("user_id", user_id).execute()
    rows = cast(list[dict], response.data)
    return rows[0] if rows else None


def hotel_of(db: Client, user_id: str) -> str | None:
    """The hotel this account works for, or None if it isn't hotel staff."""
    member = member_of(db, user_id)
    return member["hotel_id"] if member else None


def can_moderate(member: dict) -> bool:
    """Hotel admins and content moderators change and decide content; creators only upload."""
    return member["role"] in MODERATORS


def list_members(db: Client, hotel_id: str) -> list[dict]:
    response = (
        db.table("hotel_members")
        .select("user_id, email, role, created_at")
        .eq("hotel_id", hotel_id)
        .order("created_at")
        .execute()
    )
    return cast(list[dict], response.data)


def remove_member(db: Client, hotel_id: str, user_id: str) -> None:
    """Take a staff account's access to this hotel away. The Supabase account stays, with no
    access; its open session gets 403 on its next request."""
    db.table("hotel_members").delete().eq("hotel_id", hotel_id).eq("user_id", user_id).execute()


def set_role(db: Client, hotel_id: str, user_id: str, role: str) -> None:
    """Change a staff account's role in this hotel; it applies on the account's next request."""
    db.table("hotel_members").update({"role": role}).eq("hotel_id", hotel_id).eq(
        "user_id", user_id
    ).execute()
