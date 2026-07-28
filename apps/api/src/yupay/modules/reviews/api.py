"""Public surface of the ``reviews`` module — the only thing other modules import."""

from yupay.modules.reviews.models import BrandRatingStats, Review, ReviewReport
from yupay.modules.reviews.routes import admin_router, router
from yupay.modules.reviews.schemas import ReviewStatsOut
from yupay.modules.reviews.service import get_stats, recompute_all_stats

__all__ = [
    "BrandRatingStats",
    "Review",
    "ReviewReport",
    "ReviewStatsOut",
    "admin_router",
    "get_stats",
    "recompute_all_stats",
    "router",
]
