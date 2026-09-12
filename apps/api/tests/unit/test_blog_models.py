"""Pin the blog schema's table and constraint names.

These names are load-bearing for migration 0075 and for the public/admin
routes that filter on ``status`` / ``locale`` / ``slug``.
"""

from __future__ import annotations

from yupay.modules.blog.models import (
    BlogPost,
    BlogPostBrand,
    BlogPostFaq,
    BlogPostLike,
    BlogPostTranslation,
    BlogPostView,
)


def test_post_kind_and_status_constraints_use_the_naming_convention() -> None:
    """Bare CHECK suffixes become ``ck_blog_posts_{kind,status}_known``."""
    assert BlogPost.__tablename__ == "blog_posts"
    names = {c.name for c in BlogPost.__table__.constraints}  # type: ignore[attr-defined]
    assert "ck_blog_posts_kind_known" in names
    assert "ck_blog_posts_status_known" in names


def test_translation_slug_is_unique_per_locale() -> None:
    names = {c.name for c in BlogPostTranslation.__table__.constraints}  # type: ignore[attr-defined]
    assert "uq_blog_post_translations_locale_slug" in names
    assert "ck_blog_post_translations_locale_known" in names
    slug_type = BlogPostTranslation.__table__.c.slug.type
    assert getattr(slug_type, "length", None) == 96


def test_extra_brands_are_a_composite_pk() -> None:
    assert BlogPostBrand.__tablename__ == "blog_post_brands"
    pk = {col.name for col in BlogPostBrand.__table__.primary_key}
    assert pk == {"post_id", "brand_id"}


def test_faq_sort_is_unique_per_post_locale() -> None:
    names = {c.name for c in BlogPostFaq.__table__.constraints}  # type: ignore[attr-defined]
    assert "uq_blog_post_faqs_post_locale_sort" in names
    assert "ck_blog_post_faqs_locale_known" in names


def test_like_and_view_are_per_reader() -> None:
    assert BlogPostLike.__tablename__ == "blog_post_likes"
    assert {col.name for col in BlogPostLike.__table__.primary_key} == {"post_id", "reader_hash"}
    assert BlogPostView.__tablename__ == "blog_post_views"
    assert {col.name for col in BlogPostView.__table__.primary_key} == {"post_id", "reader_hash"}
    assert "like_count" in BlogPost.__table__.c
    assert "view_count" in BlogPost.__table__.c
