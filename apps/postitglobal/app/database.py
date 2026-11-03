from functools import lru_cache

from app.config import get_settings
from supabase import Client, create_client


@lru_cache
def get_supabase() -> Client:
    """
    Returns a Supabase client using the Secret key (formerly service_role).
    Used for server-side operations (bypasses RLS).
    Cache ensures a single instance per process.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_supabase_anon() -> Client:
    """
    Returns a Supabase client using the Publishable key (formerly anon).
    Use when respecting RLS policies (e.g. user-facing reads).
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)
