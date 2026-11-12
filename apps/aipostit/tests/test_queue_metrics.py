"""The job queue's metrics: tasks waiting in Redis and how long the oldest has waited, read
by the API at each scrape (the worker isn't scraped)."""

import json
import time
from typing import Any

import fakeredis
import pytest
from celery.signals import before_task_publish
from prometheus_client import CollectorRegistry, generate_latest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.jobs import queue_metrics, tasks  # noqa: F401  (tasks connects the publish signal)
from app.main import create_app


def message(published_at: float | None) -> str:
    """A task as Celery's Redis transport stores it, as far as the metrics read it."""
    headers: dict[str, Any] = {"task": "tasks.generate_content", "id": "an-id"}
    if published_at is not None:
        headers[queue_metrics.PUBLISHED_AT_HEADER] = published_at
    return json.dumps({"body": "e30=", "headers": headers, "properties": {}})


def scrape(store: Any) -> str:
    registry = CollectorRegistry()
    queue_metrics.register(registry, store)
    return generate_latest(registry).decode()


def sample(text: str, name: str) -> float:
    (line,) = [line for line in text.splitlines() if line.startswith(name + " ")]
    return float(line.split()[1])


def test_an_empty_queue_reads_zero() -> None:
    text = scrape(fakeredis.FakeRedis(decode_responses=True))
    assert sample(text, "celery_queue_length") == 0
    assert sample(text, "celery_queue_oldest_task_age_seconds") == 0


def test_waiting_tasks_are_counted_and_the_oldest_is_timed() -> None:
    store = fakeredis.FakeRedis(decode_responses=True)
    now = time.time()
    # Celery queues with LPUSH and the worker takes with BRPOP: the oldest is at the tail.
    for age in (90, 30, 5):
        store.lpush(queue_metrics.QUEUE_KEY, message(now - age))

    text = scrape(store)
    assert sample(text, "celery_queue_length") == 3
    assert 90 <= sample(text, "celery_queue_oldest_task_age_seconds") < 95


def test_a_task_without_a_publish_time_is_counted_with_no_age() -> None:
    # Queued by a release from before the header existed.
    store = fakeredis.FakeRedis(decode_responses=True)
    store.lpush(queue_metrics.QUEUE_KEY, message(None))

    text = scrape(store)
    assert sample(text, "celery_queue_length") == 1
    assert sample(text, "celery_queue_oldest_task_age_seconds") == 0


class DownRedis:
    def llen(self, key: str) -> int:
        raise RedisConnectionError("Connection refused")


def test_redis_down_reports_no_queue_metrics_and_the_scrape_still_answers() -> None:
    assert "celery_queue" not in scrape(DownRedis())


def test_publishing_a_task_stamps_its_publish_time() -> None:
    headers: dict[str, Any] = {}
    before = time.time()
    before_task_publish.send(sender="tasks.generate_content", headers=headers, body=())
    assert before <= headers[queue_metrics.PUBLISHED_AT_HEADER] <= time.time()


def test_the_app_serves_the_queue_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    store = fakeredis.FakeRedis(decode_responses=True)
    store.lpush(queue_metrics.QUEUE_KEY, message(time.time()))
    monkeypatch.setattr(queue_metrics, "queue_store", lambda: store)

    text = generate_latest(create_app().state.metrics.registry).decode()
    assert sample(text, "celery_queue_length") == 1
