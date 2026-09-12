"""Public surface of the ``blog`` module — the only thing other modules import."""

from yupay.modules.blog.admin_routes import router as admin_router
from yupay.modules.blog.indexnow import INDEXNOW_QUEUE_CHANNEL, drain_pending_pings
from yupay.modules.blog.models import (
    BlogIndexNowPing,
    BlogPost,
    BlogPostBrand,
    BlogPostFaq,
    BlogPostLike,
    BlogPostTranslation,
    BlogPostView,
)
from yupay.modules.blog.routes import router

__all__ = [
    "INDEXNOW_QUEUE_CHANNEL",
    "BlogIndexNowPing",
    "BlogPost",
    "BlogPostBrand",
    "BlogPostFaq",
    "BlogPostLike",
    "BlogPostTranslation",
    "BlogPostView",
    "admin_router",
    "drain_pending_pings",
    "router",
]
