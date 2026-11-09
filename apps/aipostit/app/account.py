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
        "avatar_url": metadata.get("avatar_url") or None,
        "role": member["role"] if member else None,
        "role_label": ROLE_LABELS_TR[member["role"]] if member else None,
    }
