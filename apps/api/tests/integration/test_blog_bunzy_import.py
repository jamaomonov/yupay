"""Bunzy → blog drafts (ADR-0077).

Two promises are made to the operator and both are tested here: an imported
article never publishes itself, and a re-sync never overwrites a person's
edit. The rest is mapping — which upstream field lands in which column.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id
from yupay.modules.blog.admin_service import publish_post, schedule_post
from yupay.modules.blog.bunzy_client import BunzyPost, BunzySummary
from yupay.modules.blog.bunzy_import import stale_slugs, sync_post
from yupay.modules.blog.models import BlogImportedPost, BlogPost, BlogPostTranslation
from yupay.modules.catalog.models import Brand, Category

pytestmark = pytest.mark.asyncio

# An excerpt of the first article they actually delivered: the five heading
# levels it uses, a link inside a sentence, both list kinds, and the one
# inline image — on their CDN, which is why it cannot come with us.
_MARKDOWN = """Самый быстрый способ пополнить Steam в Узбекистане: оплатить в сумах картой Uzcard.

## Почему геймеры ищут удобный способ

Спрос огромен ([DemandSage](https://www.demandsage.com/steam-statistics/), 2026).

1. Откройте сайт сервиса.
2. Введите логин своего аккаунта Steam.

![Игровая станция](https://cdn.bunzy.io/media/inline/6aa/f4d.jpg)

## Частые ошибки

- Неверный логин Steam.
- Слишком маленькая сумма.
"""


def _payload(**overrides: object) -> BunzyPost:
    body = {
        "slug": "steam",
        "title": "Как пополнить Steam в Узбекистане: полная инструкция",
        "excerpt": "Картами Uzcard и Humo в сумах без комиссии.",
        "markdown": _MARKDOWN,
        "language": "ru",
        "tags": ["steam", "платежи"],
        "keyTakeaways": [
            "Пополнить Steam проще всего через локальный сервис.",
            "Минимальная сумма — 10 евро или эквивалент.",
        ],
        "labels": {"keyTakeaways": "Главное", "faq": "Часто задаваемые вопросы"},
        "faq": [
            {"question": "Можно ли платить картой Uzcard?", "answer": "Напрямую — нет."},
            {"question": "Сколько идёт зачисление?", "answer": "Секунды или минуты."},
        ],
        "seo": {
            "metaTitle": "Как пополнить Steam в Узбекистане",
            "metaDescription": "Пошаговая инструкция и сроки зачисления.",
            "canonicalUrl": "https://yupay.uz/blog/steam",
            "ogImage": "https://cdn.bunzy.io/media/thumbnails/x.webp",
        },
        "author": {"name": "Jam Omonov"},
        "thumbnailUrl": "https://cdn.bunzy.io/media/thumbnails/x.webp",
        "readingMinutes": 5,
        "publishedAt": "2026-09-15T11:01:39.515Z",
        "updatedAt": "2026-09-15T11:01:39.521Z",
    }
    body.update(overrides)
    return BunzyPost.model_validate(body)


async def _brand(db: AsyncSession) -> str:
    category = Category(id=new_id(), slug=f"games-{new_id()[:8]}")
    db.add(category)
    await db.flush()
    brand = Brand(id=new_id(), slug=f"steam-{new_id()[:8]}", category_id=category.id)
    db.add(brand)
    await db.flush()
    return brand.id


async def _translation(db: AsyncSession, post_id: str) -> BlogPostTranslation:
    return (
        await db.execute(select(BlogPostTranslation).where(BlogPostTranslation.post_id == post_id))
    ).scalar_one()


async def test_an_imported_article_lands_as_a_brandless_draft(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload())
    await db_session.commit()

    assert result.outcome == "created"
    post = await db_session.get(BlogPost, result.post_id)
    assert post is not None
    assert post.status == "draft"
    assert post.primary_brand_id is None
    assert post.kind == "guide"


async def test_the_formatting_arrives_intact(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload())
    await db_session.commit()
    row = await _translation(db_session, str(result.post_id))

    assert "<h2>Почему геймеры ищут удобный способ</h2>" in row.body_html
    assert '<a href="https://www.demandsage.com/steam-statistics/">DemandSage</a>' in row.body_html
    assert "<ol>\n<li>Откройте сайт сервиса.</li>" in row.body_html
    assert "<li>Неверный логин Steam.</li>" in row.body_html
    # Their CDN is not our media origin, so the picture cannot come along.
    assert "cdn.bunzy.io" not in row.body_html
    assert "<img" not in row.body_html


async def test_the_stored_body_is_what_the_allowlist_accepts(db_session: AsyncSession) -> None:
    # The import validates on the way in rather than leaving it to publish,
    # so a construct the mapping cannot handle is a named log line on the day
    # it arrives instead of a refused publish a week later.
    from yupay.modules.blog.sanitize import sanitize_body

    result = await sync_post(db_session, _payload())
    await db_session.commit()
    row = await _translation(db_session, str(result.post_id))

    assert (
        sanitize_body(row.body_html, media_base_url="https://cdn.yupay.uz", allow_empty=False)
        == row.body_html
    )


async def test_the_key_takeaways_box_comes_with_the_article(db_session: AsyncSession) -> None:
    # We have no column for them and they are the summary a reader sees
    # first, so they go back into the body under the feed's own label.
    result = await sync_post(db_session, _payload())
    await db_session.commit()
    row = await _translation(db_session, str(result.post_id))

    assert row.body_html.startswith("<h2>Главное</h2>")
    assert "<li>Минимальная сумма — 10 евро или эквивалент.</li>" in row.body_html


async def test_the_faq_lands_in_its_own_table(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload())
    await db_session.commit()
    post = await db_session.get(BlogPost, result.post_id)
    assert post is not None

    assert [row.question for row in post.faqs] == [
        "Можно ли платить картой Uzcard?",
        "Сколько идёт зачисление?",
    ]
    assert [row.sort_order for row in post.faqs] == [0, 1]
    assert {row.locale for row in post.faqs} == {"ru"}


async def test_the_seo_block_is_carried_over(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload())
    await db_session.commit()
    row = await _translation(db_session, str(result.post_id))

    assert row.slug == "steam"
    assert row.seo_title == "Как пополнить Steam в Узбекистане"
    assert row.seo_description == "Пошаговая инструкция и сроки зачисления."
    assert row.excerpt == "Картами Uzcard и Humo в сумах без комиссии."


async def test_an_unchanged_article_is_not_rewritten(db_session: AsyncSession) -> None:
    first = await sync_post(db_session, _payload())
    await db_session.commit()

    again = await sync_post(db_session, _payload())
    await db_session.commit()

    assert again.outcome == "unchanged"
    assert again.post_id == first.post_id
    assert (
        await db_session.execute(select(BlogPost.id).where(BlogPost.id == first.post_id))
    ).scalar_one() == first.post_id


async def test_an_upstream_rewrite_refreshes_our_untouched_draft(db_session: AsyncSession) -> None:
    first = await sync_post(db_session, _payload())
    await db_session.commit()

    revised = await sync_post(
        db_session,
        _payload(title="Как пополнить Steam: обновлено", markdown=_MARKDOWN + "\n## Ещё\n"),
    )
    await db_session.commit()

    assert revised.outcome == "refreshed"
    assert revised.post_id == first.post_id
    row = await _translation(db_session, str(first.post_id))
    assert row.title == "Как пополнить Steam: обновлено"
    assert "<h2>Ещё</h2>" in row.body_html


async def test_an_edited_draft_is_never_overwritten(db_session: AsyncSession) -> None:
    # This is the promise the operator is relying on: "я проверю, поправлю и
    # опубликую сам". One touched field ends the sync for that article.
    first = await sync_post(db_session, _payload())
    await db_session.commit()
    row = await _translation(db_session, str(first.post_id))
    row.body_html = row.body_html.replace("Uzcard", "Uzcard/Humo")
    await db_session.commit()

    result = await sync_post(db_session, _payload(title="Совсем другой заголовок"))
    await db_session.commit()

    assert result.outcome == "edited"
    kept = await _translation(db_session, str(first.post_id))
    assert "Uzcard/Humo" in kept.body_html
    assert kept.title == "Как пополнить Steam в Узбекистане: полная инструкция"


async def test_an_edited_title_alone_also_stops_the_sync(db_session: AsyncSession) -> None:
    first = await sync_post(db_session, _payload())
    await db_session.commit()
    row = await _translation(db_session, str(first.post_id))
    row.title = "Мой заголовок"
    await db_session.commit()

    result = await sync_post(db_session, _payload(excerpt="другой анонс"))
    await db_session.commit()

    assert result.outcome == "edited"
    assert (await _translation(db_session, str(first.post_id))).title == "Мой заголовок"


async def test_a_published_post_is_left_alone(db_session: AsyncSession) -> None:
    first = await sync_post(db_session, _payload())
    post = await db_session.get(BlogPost, first.post_id)
    assert post is not None
    post.primary_brand_id = await _brand(db_session)
    await publish_post(db_session, post.id)
    await db_session.commit()

    result = await sync_post(db_session, _payload(title="Апдейт от Bunzy"))
    await db_session.commit()

    assert result.outcome == "locked"
    assert (await _translation(db_session, str(first.post_id))).title != "Апдейт от Bunzy"


async def test_a_slug_someone_else_holds_does_not_collide(db_session: AsyncSession) -> None:
    existing = BlogPost(
        id=new_id(),
        kind="guide",
        status="draft",
        primary_brand_id=await _brand(db_session),
        translations=[
            BlogPostTranslation(locale="ru", slug="steam", title="Наш старый гайд", excerpt="")
        ],
    )
    db_session.add(existing)
    await db_session.flush()

    result = await sync_post(db_session, _payload())
    await db_session.commit()

    assert result.outcome == "created"
    assert (await _translation(db_session, str(result.post_id))).slug == "steam-2"


async def test_an_unsupported_language_is_skipped(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload(language="kk"))
    await db_session.commit()

    assert result.outcome == "locale"
    assert (await db_session.execute(select(BlogPost.id))).first() is None


async def test_publishing_without_a_brand_is_refused(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload())
    await db_session.commit()

    with pytest.raises(ValidationError, match="brand"):
        await publish_post(db_session, str(result.post_id))


async def test_scheduling_without_a_brand_is_refused(db_session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    result = await sync_post(db_session, _payload())
    await db_session.commit()

    with pytest.raises(ValidationError, match="brand"):
        await schedule_post(
            db_session,
            str(result.post_id),
            datetime.now(UTC) + timedelta(days=1),
        )


async def test_the_database_refuses_a_brandless_post_that_is_not_a_draft(
    db_session: AsyncSession,
) -> None:
    # The service checks first; this is the constraint behind it, so a path
    # that forgets the check still cannot put a brandless post in front of a
    # reader — every storefront query reaches an article through its brand.
    from sqlalchemy.exc import IntegrityError

    result = await sync_post(db_session, _payload())
    await db_session.commit()
    post = await db_session.get(BlogPost, result.post_id)
    assert post is not None
    post.status = "published"

    with pytest.raises(IntegrityError, match="brand_unless_draft"):
        await db_session.commit()
    await db_session.rollback()


async def test_the_constraint_carries_the_name_the_orm_declares(
    db_session: AsyncSession,
) -> None:
    # ``core/db.py``'s naming convention re-templates ``ck_`` names even when
    # a migration passes one explicitly, so ``name="ck_blog_posts_x"`` ships
    # as ``ck_blog_posts_ck_blog_posts_x`` and silently stops matching the
    # model. This caught exactly that on 0079; keep it catching the next one.
    from sqlalchemy import text

    names = set(
        (
            await db_session.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'blog_posts'::regclass AND contype = 'c'"
                )
            )
        ).scalars()
    )
    assert "ck_blog_posts_brand_unless_draft" in names


async def test_only_changed_articles_are_fetched_again(db_session: AsyncSession) -> None:
    # The feed already carries ``updatedAt``; re-downloading every article
    # every hour to learn nothing changed is the request we do not make.
    await sync_post(db_session, _payload())
    await db_session.commit()

    same = BunzySummary.model_validate(
        {"slug": "steam", "title": "…", "updatedAt": "2026-09-15T11:01:39.521Z"}
    )
    moved = BunzySummary.model_validate(
        {"slug": "steam", "title": "…", "updatedAt": "2026-09-16T08:00:00.000Z"}
    )
    fresh = BunzySummary.model_validate({"slug": "new-one", "title": "…", "updatedAt": None})

    assert await stale_slugs(db_session, [same]) == []
    assert await stale_slugs(db_session, [moved]) == ["steam"]
    assert await stale_slugs(db_session, [same, fresh]) == ["new-one"]


async def test_the_ledger_records_what_we_pulled(db_session: AsyncSession) -> None:
    result = await sync_post(db_session, _payload())
    await db_session.commit()

    record = (await db_session.execute(select(BlogImportedPost))).scalar_one()
    assert record.source == "bunzy"
    assert record.external_id == "steam"
    assert record.post_id == result.post_id
    assert record.source_updated_at is not None
