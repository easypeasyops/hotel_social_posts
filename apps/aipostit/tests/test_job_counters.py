"""The job counters: the worker isn't scraped, so it adds to counters in Redis and the API
exports them. Tasks by outcome (Celery's signals), translations DeepL didn't return, and
posts Buffer couldn't send."""

from typing import Any

import fakeredis
import pytest
from prometheus_client import CollectorRegistry, generate_latest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.jobs import queue_metrics
from app.jobs.tasks import celery_app


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeRedis:
    """One Redis for the worker's counting and the API's scrape."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(queue_metrics, "queue_store", lambda: redis)
    return redis


def scrape(store: Any) -> str:
    registry = CollectorRegistry()
    queue_metrics.register(registry, store)
    return generate_latest(registry).decode()


def test_a_count_in_the_worker_is_a_counter_in_the_api(store: fakeredis.FakeRedis) -> None:
    queue_metrics.count("aipostit_translations_failed", language="de")
    queue_metrics.count("aipostit_translations_failed", language="de")
    queue_metrics.count("aipostit_translations_failed", language="ru")
    queue_metrics.count("aipostit_posts_failed")

    text = scrape(store)
    assert 'aipostit_translations_failed_total{language="de"} 2.0' in text
    assert 'aipostit_translations_failed_total{language="ru"} 1.0' in text
    assert "aipostit_posts_failed_total 1.0" in text


@celery_app.task(name="tests.succeeds")
def succeeds() -> None:
    return None


@celery_app.task(name="tests.fails")
def fails() -> None:
    raise RuntimeError("no")


@celery_app.task(name="tests.retries_once_then_fails", bind=True, max_retries=1)
def retries_once_then_fails(self: Any) -> None:
    try:
        raise RuntimeError("still no")
    except RuntimeError as exc:
        raise self.retry(exc=exc, countdown=0) from exc


def test_each_task_is_counted_by_its_outcome(store: fakeredis.FakeRedis) -> None:
    succeeds.apply()
    succeeds.apply()
    fails.apply()
    retries_once_then_fails.apply()

    text = scrape(store)
    assert 'celery_tasks_total{outcome="success",task="tests.succeeds"} 2.0' in text
    assert 'celery_tasks_total{outcome="failure",task="tests.fails"} 1.0' in text
    # A retry is not yet a failure; the failure is counted once, when the retries run out.
    assert 'celery_tasks_total{outcome="retry",task="tests.retries_once_then_fails"} 1.0' in text
    assert 'celery_tasks_total{outcome="failure",task="tests.retries_once_then_fails"} 1.0' in text


def test_a_field_this_release_does_not_know_is_left_out(store: fakeredis.FakeRedis) -> None:
    # Written by a newer or older release that shares the Redis during a rollout.
    store.hset(queue_metrics.COUNTERS_KEY, "aipostit_something_else|x", 3)
    store.hset(queue_metrics.COUNTERS_KEY, "aipostit_translations_failed|de|extra", 3)
    store.hset(queue_metrics.COUNTERS_KEY, "aipostit_posts_failed", "not a number")
    samples = [line for line in scrape(store).splitlines() if not line.startswith("#")]
    assert not [line for line in samples if line.startswith("aipostit_")]


class DownRedis:
    def hincrby(self, *args: Any) -> int:
        raise RedisConnectionError("Connection refused")


def test_counting_never_fails_the_task(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(queue_metrics, "queue_store", DownRedis)
    queue_metrics.count("aipostit_posts_failed")  # no exception
    assert "could not count aipostit_posts_failed" in caplog.text
