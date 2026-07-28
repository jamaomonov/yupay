"""Public surface of the ``realtime`` module."""

from yupay.modules.realtime.routes import router
from yupay.modules.realtime.service import publish_order_event

__all__ = ["publish_order_event", "router"]
