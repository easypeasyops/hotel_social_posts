"""The signed-in account as people see it, for the profile pages: its name is Supabase
user_metadata.full_name, the key Google sign-in fills too."""

from typing import Any


def full_name(user: Any) -> str:
    """The name the account gave, or "" if it has none."""
    metadata = getattr(user, "user_metadata", None) or {}
    return str(metadata.get("full_name") or "").strip()
