"""The job system's metrics, exported by the API: the worker isn't scraped (the chart gives
workers no Service), and Redis is where both meet.

* The queue: how many tasks wait in Redis, and how long the oldest has waited, read at each
  scrape. A worker that hangs without exiting keeps its pod Running; what shows it is tasks
  waiting ever longer.
* Counters: what the worker did. It adds to a Redis hash (`count`), which the API reads at
  each scrape. Redis keeps them across restarts of either; if its data is lost they start
  again from 0, which Prometheus reads as any counter reset.
"""

import json
import logging
import time
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Final

from prometheus_client import CollectorRegistry
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
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

# The counters: a Redis hash whose fields are a counter's name and its label values in
# order, joined by "|" ("celery_tasks|tasks.generate_content|success"), each holding a count.
COUNTERS_KEY: Final = "aipostit:job-counters"
# name (Prometheus adds _total) -> (help, label names)
COUNTERS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "celery_tasks": (
        "Tasks the worker finished, by outcome: success, retry (it will run again) or failure.",
        ("task", "outcome"),
    ),
    "aipostit_translations_failed": ("Translations DeepL didn't return.", ("language",)),
    "aipostit_posts_failed": ("Posts Buffer couldn't send.", ()),
}

log = logging.getLogger(__name__)


@lru_cache
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


def count(counter: str, **labels: str) -> None:
    """Add one to a counter (worker side). Never fails its caller: a count that can't be
    written is logged and lost."""
    field = "|".join([counter, *(labels[name] for name in COUNTERS[counter][1])])
    try:
        queue_store().hincrby(COUNTERS_KEY, field, 1)
    except RedisError as exc:
        log.warning("could not count %s: %s", field, exc)


def _counters(fields: dict[str, str]) -> Iterator[CounterMetricFamily]:
    families = {
        name: CounterMetricFamily(name, text, labels=list(label_names))
        for name, (text, label_names) in COUNTERS.items()
    }
    for field, value in fields.items():
        name, *label_values = field.split("|")
        # A field another release wrote (a rollout shares the Redis) may not fit: skip it.
        if name in families and len(label_values) == len(COUNTERS[name][1]) and value.isdigit():
            families[name].add_metric(label_values, int(value))
    yield from families.values()


class QueueCollector(Collector):
    def __init__(self, store: Any) -> None:
        self.store = store

    def collect(self) -> Iterator[Metric]:
        try:
            length = self.store.llen(QUEUE_KEY)
            oldest = self.store.lindex(QUEUE_KEY, -1)
            counters = self.store.hgetall(COUNTERS_KEY)
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
        yield from _counters(counters)


def register(registry: CollectorRegistry, store: Any) -> None:
    registry.register(QueueCollector(store))
