"""Settings for tests: placeholder values for every required variable, so the app imports
without a .env; and no network: a test that reaches beyond this machine fails at once
(tests/network_guard.py)."""

import os
from collections.abc import Iterator

import pytest

from tests import network_guard

TEST_ENV = {
    "SECRET_KEY": "test-secret-key",
    "SUPABASE_URL": "https://supabase.invalid",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "DEEPL_API_KEY": "test-deepl-key",
    "BUFFER_ACCESS_TOKEN": "test-buffer-token",
    "CRON_SECRET": "test-cron-secret",
    "REDIS_URL": "redis://redis.invalid:6379/0",
    "METRICS_PORT": "0",  # no metrics server in tests; tests/test_metrics.py starts its own
}
os.environ.update(TEST_ENV)

network_guard.install()


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    """Each test reads the environment anew (get_settings is cached)."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
