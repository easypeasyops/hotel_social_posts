"""The job queue's metrics: how many tasks wait in Redis, and how long the oldest has waited.

The worker exports no metrics (the chart doesn't scrape workers), so the API reads the queue
at each scrape. A worker that hangs without exiting keeps its pod Running; what shows it is
tasks waiting ever longer.
"""

import json
import time
from collections.abc import Iterator
from typing import Any, Final

from prometheus_client import CollectorRegistry
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

# Celery's default queue: a Redis list it queues on with LPUSH and the worker takes from
# with BRPOP, so the oldest task is at the tail.
QUEUE_KEY: Final = "celery"
# When a task was queued (Unix seconds), in its message's headers (app/jobs/tasks.py).
PUBLISHED_AT_HEADER: Final = "published_at"
REDIS_TIMEOUT_SECONDS: Final = 2.0  # a hung Redis must not hold a scrape past its timeout


def queue_store() -> Redis:
    return Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
    )


def _age_seconds(raw_message: str | None) -> float:
    """How long ago the message was queued; 0 for no message or one with no publish time."""
    if raw_message is None:
        return 0.0
    try:
        published_at = float(json.loads(raw_message)["headers"][PUBLISHED_AT_HEADER])
    except ValueError, KeyError, TypeError:
        return 0.0
    return max(0.0, time.time() - published_at)


class QueueCollector(Collector):
    def __init__(self, store: Any) -> None:
        self.store = store

    def collect(self) -> Iterator[GaugeMetricFamily]:
        try:
            length = self.store.llen(QUEUE_KEY)
            oldest = self.store.lindex(QUEUE_KEY, -1)
        except RedisError:
            return  # no samples while Redis is away; the rest of the scrape still answers
        yield GaugeMetricFamily(
            "celery_queue_length", "Tasks waiting in Redis for a worker.", value=length
        )
        yield GaugeMetricFamily(
            "celery_queue_oldest_task_age_seconds",
            "How long the oldest waiting task has waited; 0 for an empty queue.",
            value=_age_seconds(oldest),
        )


def register(registry: CollectorRegistry, store: Any) -> None:
    registry.register(QueueCollector(store))
