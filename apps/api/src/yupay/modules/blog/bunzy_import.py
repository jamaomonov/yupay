"""Pull Bunzy articles in as blog **drafts**.

Nothing here publishes. An imported article lands as a ``draft`` with no
brand, and an editor reads it, attaches the brand, fixes what needs fixing
and presses publish. That is the whole contract with the operator, and two
rules keep it true:

- **Never overwrite an edit.** Every write records a fingerprint of exactly
  what it wrote. A later pass refreshes an article only when our copy still
  hashes to that fingerprint — so the moment a person touches the title, the
  body, the excerpt, the SEO fields or the FAQ, the importer stops touching
  that article for good.
- **Never touch a post that left ``draft``.** Published, scheduled and
  archived are all off limits, whether or not anyone edited them.

The formatting itself is :mod:`markdown_html`'s job; what happens here is
the *mapping* — which upstream field becomes which column, and what we do
with the pieces our schema has no room for (tags, byline, reading time and
the thumbnail, which lives on their CDN and so cannot be our cover).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.blog.bunzy_client import BunzyPost, BunzySummary
from yupay.modules.blog.markdown_html import markdown_to_html
from yupay.modules.blog.models import (
    LOCALES,
    BlogImportedPost,
    BlogPost,
    BlogPostFaq,
    BlogPostTranslation,
)
from yupay.modules.blog.sanitize import sanitize_body

log = get_logger("yupay.blog.bunzy_import")

SOURCE: Final = "bunzy"
_KIND: Final = "guide"
_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,94}[a-z0-9]$")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")
_SLUG_ATTEMPTS: Final = 20
_MAX_FAQS: Final = 100

Outcome = Literal["created", "refreshed", "unchanged", "edited", "locked", "locale"]


@dataclass(frozen=True, slots=True)
class SyncResult:
    """What one article did on one pass, for the job's summary line."""

    outcome: Outcome
    slug: str
    post_id: str | None = None


async def stale_slugs(db: AsyncSession, summaries: list[BunzySummary]) -> list[str]:
    """Which of ``summaries`` are worth a detail fetch.

    The list endpoint already carries ``updatedAt``, so an article we have
    seen at that exact revision needs no second request. Bunzy writes one
    article a day and the job runs hourly; without this every pass would
    re-download the entire feed to discover nothing changed.
    """
    if not summaries:
        return []
    known = {
        row.external_id: row
        for row in (
            await db.execute(
                select(BlogImportedPost).where(
                    BlogImportedPost.source == SOURCE,
                    BlogImportedPost.external_id.in_([s.slug for s in summaries]),
                )
            )
        ).scalars()
    }
    stale: list[str] = []
    seen_at = now()
    for summary in summaries:
        record = known.get(summary.slug)
        if record is None:
            stale.append(summary.slug)
            continue
        record.last_seen_at = seen_at
        if record.source_updated_at != _parse_ts(summary.updated_at):
            stale.append(summary.slug)
    return stale


async def sync_post(db: AsyncSession, post: BunzyPost) -> SyncResult:
    """Create or refresh one draft. Runs in the caller's transaction."""
    if post.language not in LOCALES:
        log.info("bunzy.skipped_locale", slug=post.slug, language=post.language)
        return SyncResult("locale", post.slug)
    record = await db.get(BlogImportedPost, {"source": SOURCE, "external_id": post.slug})
    if record is not None:
        record.last_seen_at = now()
        # Before rendering: an article nobody changed should cost one hash
        # comparison, not a Markdown parse.
        if record.source_hash == _source_hash(post):
            return SyncResult("unchanged", post.slug, record.post_id)
    fields = _render(post)
    if record is None:
        return await _create(db, post, fields)
    return await _refresh(db, post, fields, record)


async def _create(db: AsyncSession, post: BunzyPost, fields: _Rendered) -> SyncResult:
    """Insert a brandless draft plus its one translation and its FAQ rows."""
    slug = await _free_slug(db, _slugify(post.slug, post.title), post.language)
    row = BlogPost(
        id=new_id(),
        kind=_KIND,
        status="draft",
        # No brand: nobody has decided what this article sells yet, and the
        # CHECK on ``blog_posts`` lets a draft say so honestly instead of
        # forcing a wrong one in. Publishing refuses until it is filled.
        primary_brand_id=None,
        show_buy_card=True,
        pin_on_brand=False,
        translations=[_translation(post.language, slug, fields)],
        faqs=_faqs(post, post.language),
    )
    db.add(row)
    await db.flush()
    db.add(
        BlogImportedPost(
            source=SOURCE,
            external_id=post.slug,
            post_id=row.id,
            source_hash=_source_hash(post),
            rendered_hash=_rendered_hash(slug, fields, row.faqs),
            source_updated_at=_parse_ts(post.updated_at),
        )
    )
    log.info(
        "bunzy.created",
        slug=post.slug,
        post_id=row.id,
        locale=post.language,
        dropped_images=fields.dropped_images,
        unwrapped_links=fields.unwrapped_links,
        faqs=len(row.faqs),
    )
    return SyncResult("created", post.slug, row.id)


async def _refresh(
    db: AsyncSession, post: BunzyPost, fields: _Rendered, record: BlogImportedPost
) -> SyncResult:
    """Rewrite our copy — but only while it is still, byte for byte, ours."""
    row = await db.get(BlogPost, record.post_id)
    if row is None:  # pragma: no cover - the FK cascades, so this cannot happen
        return SyncResult("edited", post.slug)
    if row.status != "draft":
        log.info("bunzy.locked", slug=post.slug, post_id=row.id, status=row.status)
        return SyncResult("locked", post.slug, row.id)
    translation = next((t for t in row.translations if t.locale == post.language), None)
    if (
        translation is None
        or _rendered_hash(translation.slug, _of(translation), row.faqs) != record.rendered_hash
    ):
        log.info("bunzy.edited", slug=post.slug, post_id=row.id)
        return SyncResult("edited", post.slug, row.id)
    translation.title = fields.title
    translation.excerpt = fields.excerpt
    translation.body_html = fields.body_html
    translation.seo_title = fields.seo_title
    translation.seo_description = fields.seo_description
    row.faqs.clear()
    await db.flush()
    row.faqs = _faqs(post, post.language)
    row.updated_at = now()
    await db.flush()
    record.source_hash = _source_hash(post)
    record.rendered_hash = _rendered_hash(translation.slug, fields, row.faqs)
    record.source_updated_at = _parse_ts(post.updated_at)
    record.last_synced_at = now()
    log.info("bunzy.refreshed", slug=post.slug, post_id=row.id, faqs=len(row.faqs))
    return SyncResult("refreshed", post.slug, row.id)


@dataclass(frozen=True, slots=True)
class _Rendered:
    """The translation columns, already cut to their storage limits."""

    title: str
    excerpt: str
    body_html: str
    seo_title: str | None
    seo_description: str | None
    dropped_images: int = 0
    unwrapped_links: int = 0


def _render(post: BunzyPost) -> _Rendered:
    """Map one upstream article onto the translation columns."""
    converted = markdown_to_html(_source_markdown(post))
    return _Rendered(
        title=_cut(post.title, 200),
        excerpt=_cut(post.excerpt, 280),
        # Validated on the way *in*, not only at publish. The converter is
        # built to satisfy this and a test asserts it does, so a failure here
        # means the mapping met a construct it does not know — which is worth
        # a named log line now rather than a refused publish days later.
        # ``allow_empty`` matches the rest of the module: a draft may have no
        # body, publishing may not.
        body_html=sanitize_body(
            converted.html,
            media_base_url=get_settings().r2_public_base_url.rstrip("/"),
            allow_empty=True,
        ),
        seo_title=_cut(post.seo.meta_title or "", 200) or None,
        seo_description=_cut(post.seo.meta_description or "", 320) or None,
        dropped_images=converted.dropped_images,
        unwrapped_links=converted.unwrapped_links,
    )


def _of(translation: BlogPostTranslation) -> _Rendered:
    """Read the stored columns back into the same shape, to compare them."""
    return _Rendered(
        title=translation.title,
        excerpt=translation.excerpt,
        body_html=translation.body_html,
        seo_title=translation.seo_title,
        seo_description=translation.seo_description,
    )


def _source_markdown(post: BunzyPost) -> str:
    """The article, with its key-takeaways box put back on top as Markdown.

    Upstream serves those bullets beside the body rather than inside it. We
    have no column for them, and dropping them would lose the summary a
    reader sees first — so they go back into the body as the section they
    are rendered as, under the label the feed supplies in its own language.
    """
    if not post.key_takeaways:
        return post.markdown
    label = _one_line(post.labels.key_takeaways) or post.title
    bullets = "\n".join(f"- {_one_line(item)}" for item in post.key_takeaways if item.strip())
    if not bullets:
        return post.markdown
    return f"## {label}\n\n{bullets}\n\n{post.markdown}"


def _translation(locale: str, slug: str, fields: _Rendered) -> BlogPostTranslation:
    return BlogPostTranslation(
        locale=locale,
        slug=slug,
        title=fields.title,
        excerpt=fields.excerpt,
        body_html=fields.body_html,
        seo_title=fields.seo_title,
        seo_description=fields.seo_description,
    )


def _faqs(post: BunzyPost, locale: str) -> list[BlogPostFaq]:
    """Upstream Q/A → ``blog_post_faqs``, which the page and its JSON-LD share."""
    out: list[BlogPostFaq] = []
    for row in post.faq[:_MAX_FAQS]:
        question = _one_line(row.question)
        answer = row.answer.strip()
        if not question or not answer:
            continue
        out.append(
            BlogPostFaq(
                id=new_id(),
                locale=locale,
                sort_order=len(out),
                question=_cut(question, 280),
                # 2000 is the admin form's own cap: a longer answer would
                # import fine and then refuse to save on the first edit.
                answer=_cut(answer, 2000),
            )
        )
    return out


async def _free_slug(db: AsyncSession, base: str, locale: str) -> str:
    """``base``, or the first ``base-N`` no other post holds in this locale."""
    for attempt in range(1, _SLUG_ATTEMPTS + 1):
        candidate = base if attempt == 1 else _cut(base, 92 - len(str(attempt))) + f"-{attempt}"
        taken = (
            await db.execute(
                select(BlogPostTranslation.post_id).where(
                    BlogPostTranslation.locale == locale,
                    BlogPostTranslation.slug == candidate,
                )
            )
        ).first()
        if taken is None:
            return candidate
    raise ValueError(f"no free slug for {base!r} in {locale}")


def _slugify(slug: str, title: str) -> str:
    """Keep the upstream slug when our pattern accepts it; derive one if not."""
    if _SLUG_OK.match(slug):
        return slug
    derived = _NON_SLUG.sub("-", _transliterate(title.lower())).strip("-")[:96].strip("-")
    return derived if _SLUG_OK.match(derived) else f"post-{new_id()[:8]}"


_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip


def _transliterate(text: str) -> str:
    return "".join(_CYRILLIC.get(char, char) for char in text)


def _one_line(text: str) -> str:
    """Collapse to a single line so it cannot break out of a Markdown bullet."""
    return _WHITESPACE.sub(" ", text).strip()


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _source_hash(post: BunzyPost) -> str:
    """Fingerprint of every upstream field we consume — nothing else."""
    return _digest(
        {
            "title": post.title,
            "excerpt": post.excerpt,
            "markdown": post.markdown,
            "language": post.language,
            "keyTakeaways": post.key_takeaways,
            "labels": post.labels.model_dump(),
            "faq": [[row.question, row.answer] for row in post.faq],
            "seo": [post.seo.meta_title, post.seo.meta_description],
        }
    )


def _rendered_hash(slug: str, fields: _Rendered, faqs: list[BlogPostFaq]) -> str:
    """Fingerprint of everything the importer writes, so an edit is visible."""
    return _digest(
        {
            "slug": slug,
            "title": fields.title,
            "excerpt": fields.excerpt,
            "body_html": fields.body_html,
            "seo_title": fields.seo_title,
            "seo_description": fields.seo_description,
            "faq": [[row.locale, row.sort_order, row.question, row.answer] for row in faqs],
        }
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


__all__ = ["SOURCE", "SyncResult", "stale_slugs", "sync_post"]
