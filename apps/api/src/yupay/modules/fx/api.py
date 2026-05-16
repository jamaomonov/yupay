"""Public surface of the ``fx`` module."""

from yupay.modules.fx.factory import build_default_service
from yupay.modules.fx.models import FxSnapshot
from yupay.modules.fx.providers.base import Quote
from yupay.modules.fx.routes import admin_router, router
from yupay.modules.fx.schemas import RateOut, RatesOut
from yupay.modules.fx.service import ConversionResult, FxService, FxUnavailableError

__all__ = [
    "ConversionResult",
    "FxService",
    "FxSnapshot",
    "FxUnavailableError",
    "Quote",
    "RateOut",
    "RatesOut",
    "admin_router",
    "build_default_service",
    "router",
]
