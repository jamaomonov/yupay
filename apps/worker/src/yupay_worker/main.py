"""Dramatiq broker setup + actor registration.

Run as: ``dramatiq yupay_worker.main`` (see ``make dev-worker``).
"""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AgeLimit, Retries, ShutdownNotifications, TimeLimit
from yupay.core.config import get_settings
from yupay.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("yupay.worker")

_settings = get_settings()

broker = RedisBroker(url=_settings.dramatiq_broker_url)  # type: ignore[no-untyped-call]
broker.add_middleware(AgeLimit())
broker.add_middleware(TimeLimit())
broker.add_middleware(ShutdownNotifications())
broker.add_middleware(Retries(max_retries=5, min_backoff=1_000, max_backoff=300_000))

dramatiq.set_broker(broker)


@dramatiq.actor(queue_name="default", max_retries=0)
def ping(message: str = "pong") -> None:
    """Trivial smoke actor used by ``make dev-worker`` to confirm wiring."""
    log.info("worker.ping", message=message)
