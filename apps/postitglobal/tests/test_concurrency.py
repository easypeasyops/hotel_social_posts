"""A slow Supabase call must not stall other requests. The Supabase, Redis and Celery
clients are synchronous, so route handlers and dependencies that use them are plain `def`:
FastAPI runs those in its thread pool. An `async def` handler calling them would run on the
event loop and block every other request until the call returned."""

import asyncio
import time
from typing import Any

import httpx
import pytest

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.hotels import service
from app.main import create_app

SLOW = 0.5  # seconds the stand-in Supabase call takes


def test_a_slow_database_call_does_not_block_other_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow_list_hotels(db: Any) -> list[dict[str, str]]:
        time.sleep(SLOW)  # what a blocking HTTP call to Supabase does
        return []

    monkeypatch.setattr(service, "list_hotels", slow_list_hotels)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": "operator"}
    app.dependency_overrides[get_supabase] = lambda: object()

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Timed from before the slow request starts: a blocked event loop also holds
            # up this coroutine's own sleep, so timing from after it would miss the block.
            started = time.perf_counter()
            slow = asyncio.create_task(client.get("/api/v1/hotels"))
            await asyncio.sleep(0.05)  # the slow request is in its database call now
            health = await client.get("/healthz")
            answered_after = time.perf_counter() - started
            assert health.status_code == 200
            assert (await slow).status_code == 200
            return answered_after

    assert asyncio.run(scenario()) < SLOW / 2
