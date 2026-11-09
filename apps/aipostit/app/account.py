"""The signed-in account as people see it, for the profile pages: its name is Supabase
user_metadata.full_name, the key Google sign-in fills too."""

from typing import Any

from app.hotels.staff import ROLE_LABELS_TR


def full_name(user: Any) -> str:
    """The name the account gave, or "" if it has none."""
    metadata = getattr(user, "user_metadata", None) or {}
    return str(metadata.get("full_name") or "").strip()


def display_name(user: Any) -> str:
    """The account's name, or its email's local part while it has none."""
    return full_name(user) or (getattr(user, "email", None) or "").split("@")[0]


def menu(user: Any, member: dict | None = None) -> dict:
    """What the top bar's user menu shows: the name, its initials, a photo if Google gave one,
    and for hotel staff their role."""
    name = display_name(user)
    words = name.split()
    metadata = getattr(user, "user_metadata", None) or {}
    return {
        "name": name,
        "first_name": words[0] if words else "",
        "initials": "".join(w[0] for w in words[:1] + words[1:][-1:]).upper() or "?",
        "email": getattr(user, "email", None) or "",
        # The photo the account uploaded (app/profile_photo.py), else the one Google gave.
        "avatar_url": (
            f"/account/photo?v={metadata['photo_version']}"
            if metadata.get("photo_version")
            else metadata.get("avatar_url") or None
        ),
        "has_photo": bool(metadata.get("photo_version")),
        "role": member["role"] if member else None,
        "role_label": ROLE_LABELS_TR[member["role"]] if member else None,
    }


MAX_NAME_LENGTH = 100


def clean_full_name(name: str) -> str | None:
    """The name with its spaces collapsed, or None if it is blank or too long."""
    name = " ".join(name.split())
    return name if 0 < len(name) <= MAX_NAME_LENGTH else None


def save_full_name(db: Any, user_id: str, name: str) -> str | None:
    """Set the account's full name (clean_full_name); None, saving nothing, if it isn't one.
    Supabase merges user_metadata, so the account's other keys stay."""
    cleaned = clean_full_name(name)
    if cleaned is not None:
        db.auth.admin.update_user_by_id(user_id, {"user_metadata": {"full_name": cleaned}})
    return cleaned
