"""Notification service: format order events and dispatch through channels.

Lookups (user → telegram link, order → items) happen here so callers only
need to supply the order id. Each ``notify_*`` function is fire-and-forget:
it catches all errors so a notification failure can never roll back the
business transaction that triggered it.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
from collections.abc import Callable, Coroutine, Sequence
from decimal import Decimal
from typing import Any, Final
from urllib.parse import quote

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.fulfillment.models import Delivery
from yupay.modules.notifications.channels import telegram as tg
from yupay.modules.notifications.channels.email import send_email
from yupay.modules.notifications.templates import (
    order_confirmation_email,
    order_delivered_email,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.service import build_item_display
from yupay.modules.users.models import TelegramLink

log = get_logger("yupay.notifications.service")

# Cap delivered codes shown inline in the bot — long lists hit Telegram's 4096
# message-length limit and visually overwhelm the chat.
_MAX_INLINE_CODES: Final[int] = 5


async def _resolve_chat_id(
    db: AsyncSession, *, user_id: str | None
) -> tuple[int, str | None] | None:
    """Look up the Telegram chat id and display name for ``user_id``.

    Returns ``None`` if the user has no linked Telegram account (e.g. guest
    orders) — callers no-op silently in that case.
    """
    if user_id is None:
        return None
    stmt = select(TelegramLink).where(TelegramLink.user_id == user_id)
    link = (await db.execute(stmt)).scalar_one_or_none()
    if link is None:
        return None
    name = link.first_name or link.tg_username
    return link.tg_user_id, name


def _format_amount(value: str | Decimal, currency: str) -> str:
    try:
        amount = Decimal(value)
    except (ArithmeticError, ValueError):
        return f"{value} {currency}"
    # Two-decimal trailing zeros for fiat, three for crypto so 0.123 USDT stays exact.
    digits = 3 if currency in {"USDT", "USDC"} else 2
    return f"{amount:.{digits}f} {currency}"


_FIELD_LABEL_RU: Final[dict[str, str]] = {
    "player_id": "ID игрока",
    "user_id": "ID пользователя",
    "account_id": "Аккаунт",
    "email": "Email",
    "phone": "Телефон",
    "region": "Регион",
    "zone_id": "Zone ID",
    "character": "Персонаж",
    "nickname": "Никнейм",
}


def _format_target_fields(fields: dict[str, object]) -> str | None:
    """Render fulfilment-data fields as ``ID игрока: 123, Регион: EU``.

    ``value`` is customer-entered free text from checkout, and ``label``
    falls back to the raw (non-constant) field key when it isn't one of the
    known labels — both are escaped before splicing into the
    ``parse_mode:HTML`` Telegram message this feeds.
    """
    parts: list[str] = []
    for key, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            continue
        label = html.escape(_FIELD_LABEL_RU.get(key, key))
        parts.append(f"{label}: <code>{html.escape(value)}</code>")
    return ", ".join(parts) if parts else None


def _format_target_plain(fields: dict[str, object]) -> str | None:
    """Plain-text variant of :func:`_format_target_fields` for email bodies.

    The email template escapes text itself, so this returns raw ``label: value``
    pairs (``ID игрока: 123, Регион: EU``) with no HTML markup.
    """
    parts: list[str] = []
    for key, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            continue
        label = _FIELD_LABEL_RU.get(key, key)
        parts.append(f"{label}: {value}")
    return ", ".join(parts) if parts else None


def _credited_line_for_email(d: Delivery) -> str:
    """Build a top-up 'credited' line, echoing the target account when known.

    Only the customer's own checkout input (``fulfillment_data``) is echoed; the
    supplier's ``external_id`` is never surfaced in the email. When no target is
    known, fall back to a neutral confirmation.
    """
    snapshot = d.artifact.get("fulfillment_data")
    fields = snapshot if isinstance(snapshot, dict) else {}
    target = _format_target_plain(fields)
    if target:
        return f"Зачислено · {target}"
    return "Зачислено на ваш аккаунт"


def _delivery_lines_for_email(
    deliveries: Sequence[Delivery],
) -> tuple[list[str], list[str]]:
    """Split delivery artifacts into secret codes and top-up 'credited' lines.

    Voucher / license artifacts surface the raw code so the buyer gets their key
    straight from the email; top-up receipts deliver no code, only a short
    'credited' confirmation (with the target account when known). Both lists are
    capped together at :data:`_MAX_INLINE_CODES`.

    Returns:
        A ``(codes, credited)`` tuple of plain (non-HTML) lines.
    """
    codes: list[str] = []
    credited: list[str] = []
    for d in deliveries[:_MAX_INLINE_CODES]:
        code = d.artifact.get("code") or d.artifact.get("key")
        if isinstance(code, str) and code:
            codes.append(code)
        elif d.artifact_kind == "topup_receipt":
            credited.append(_credited_line_for_email(d))
    return codes, credited


def _summarise_order(order: Order, *, locale: str = "ru") -> str:
    """One-line product summary, e.g. ``PUBG Mobile · 660 UC +1``.

    Reuses :func:`build_item_display` so the bot copy matches the mini-app
    storefront — both pull the same localised brand / product names out of
    the eager-loaded translations chain.
    """
    items: list[OrderItem] = list(order.items)
    if not items:
        return f"Заказ {order.id[:8]}"
    display = build_item_display(items[0], locale=locale)
    if display is None:
        return f"Заказ {order.id[:8]}"
    denom = display.denomination or display.sku_code
    headline = (
        f"{display.brand_name} · {denom}"
        if display.brand_name
        else f"{display.product_name or display.product_slug} · {denom}"
    )
    extra = len(items) - 1
    if extra > 0:
        headline += f" +{extra}"
    return headline


async def _send_guest_email_confirmation(
    *,
    order_id: str,
    guest_email: str | None,
    web_base: str | None,
) -> None:
    """Email a guest buyer that their order was confirmed (best-effort).

    Args:
        order_id: The order's ID.
        guest_email: Recipient address, or ``None`` for registered users.
        web_base: Web base URL including locale prefix (e.g. ``https://yupay.uz/ru``).
            When empty (dev default) the function returns early without sending.

    No-ops silently when ``guest_email`` or ``web_base`` are absent. Any send
    failure is swallowed so a best-effort notification never breaks (or rolls
    back) the caller's order flow.
    """
    if not guest_email or not web_base:
        return
    link = f"{web_base.rstrip('/')}/orders/{order_id}"
    content = order_confirmation_email(order_id=order_id, link=link)
    with contextlib.suppress(Exception):  # best-effort: never break the order flow
        await send_email(
            to=guest_email,
            subject=content.subject,
            html=content.html,
            text=content.text,
        )


def _guest_order_link(*, web_base: str, order_id: str, guest_email: str) -> str:
    """Order page URL carrying a magic-link ``guest_order`` access token.

    The token unlocks only this order's delivered codes (see ADR-0042), so the
    buyer can view them on the web straight from the email without the
    freely-mintable email-only guest token that anyone knowing the address could
    forge. Falls back to a plain link if the email pepper isn't configured (dev).
    """
    base = f"{web_base.rstrip('/')}/orders/{order_id}"
    pepper = get_settings().auth_email_pepper
    if not pepper:
        return base
    token = authjwt.mint_guest_order(
        order_id=order_id, email_hash=email_hash(guest_email, pepper)
    )
    # ``email`` rides the link so the order page can send it back as the
    # ``X-Guest-Email`` header the deliveries endpoint checks against the token's
    # hash — the same header the rest of the guest surface already uses.
    return f"{base}?access={token}&email={quote(guest_email)}"


async def _send_guest_email_delivered(
    *,
    order_id: str,
    guest_email: str | None,
    web_base: str | None,
    codes: list[str] | None = None,
    credited: list[str] | None = None,
) -> None:
    """Email a guest buyer that their order was delivered (best-effort).

    Args:
        order_id: The order's ID.
        guest_email: Recipient address, or ``None`` for registered users.
        web_base: Web base URL including locale prefix (e.g. ``https://yupay.uz/ru``).
            When empty (dev default) the function returns early without sending.
        codes: Voucher/license keys to render inline as monospace chips, so the
            buyer gets their secret straight from the email. ``None`` => none.
        credited: Top-up 'credited' lines (no secret code) rendered as info rows.
            ``None`` => none. When both ``codes`` and ``credited`` are empty the
            email is link-only.

    No-ops silently when ``guest_email`` or ``web_base`` are absent. Any send
    failure is swallowed so a best-effort notification never breaks (or rolls
    back) the caller's order flow.
    """
    if not guest_email or not web_base:
        return
    link = _guest_order_link(web_base=web_base, order_id=order_id, guest_email=guest_email)
    content = order_delivered_email(order_id=order_id, link=link, codes=codes, credited=credited)
    with contextlib.suppress(Exception):  # best-effort: never break the order flow
        await send_email(
            to=guest_email,
            subject=content.subject,
            html=content.html,
            text=content.text,
        )


async def notify_order_paid(order_id: str) -> bool:
    """Telegram + email: «Заказ оплачен, передаём в выдачу». Returns Telegram success."""
    async with get_session_factory()() as db:
        order = await _load_order(db, order_id)
        if order is None:
            return False
        chat = await _resolve_chat_id(db, user_id=order.user_id)
        guest_email: str | None = order.guest_email

    # Email confirmation for guest buyers — best-effort, independent of Telegram.
    settings = get_settings()
    await _send_guest_email_confirmation(
        order_id=order_id,
        guest_email=guest_email,
        web_base=settings.web_base_url or None,
    )

    if chat is None:
        return False
    chat_id, name = chat

    token = settings.telegram_bot_token
    if not token:
        log.info("notify.skipped.no_token", event="order.paid", order_id=order_id)
        return False

    summary = _summarise_order(order)
    amount = _format_amount(order.total_charged, order.currency)
    text = (
        f"<b>Оплата получена</b>\n\n"
        f"{summary}\n"
        f"Сумма: <b>{amount}</b>\n\n"
        f"<i>Передаём заказ в выдачу — пришлём код как только будет готово.</i>"
    )
    result: bool = await tg.send_message(bot_token=token, chat_id=chat_id, text=text)
    return result


async def notify_order_delivered(order_id: str) -> bool:
    """Telegram + email: «Заказ выдан + коды»."""
    async with get_session_factory()() as db:
        order = await _load_order(db, order_id)
        if order is None:
            return False
        chat = await _resolve_chat_id(db, user_id=order.user_id)
        guest_email: str | None = order.guest_email

        # Inline-render up to N voucher codes for the smallest-friction UX.
        # Real top-up receipts and license keys also surface here.
        deliveries = (
            (
                await db.execute(
                    select(Delivery)
                    .join(OrderItem, OrderItem.id == Delivery.order_item_id)
                    .where(OrderItem.order_id == order_id)
                    .order_by(Delivery.delivered_at)
                )
            )
            .scalars()
            .all()
        )

    settings = get_settings()

    # Email notification for guest buyers — best-effort, independent of Telegram.
    # Inline the same voucher codes / top-up receipts the Telegram message shows.
    email_codes, email_credited = _delivery_lines_for_email(deliveries)
    await _send_guest_email_delivered(
        order_id=order_id,
        guest_email=guest_email,
        web_base=settings.web_base_url or None,
        codes=email_codes,
        credited=email_credited,
    )

    if chat is None:
        return False
    chat_id, _name = chat

    token = settings.telegram_bot_token
    if not token:
        return False

    summary = _summarise_order(order)
    amount = _format_amount(order.total_charged, order.currency)

    code_lines: list[str] = []
    for d in deliveries[:_MAX_INLINE_CODES]:
        code = d.artifact.get("code") or d.artifact.get("key")
        if isinstance(code, str) and code:
            code_lines.append(f"<code>{code}</code>")
        elif d.artifact_kind == "topup_receipt":
            # Echo the player id (or whatever the user typed at checkout) so
            # they can verify we credited the right account at a glance.
            snapshot = d.artifact.get("fulfillment_data")
            fields = snapshot if isinstance(snapshot, dict) else {}
            target = _format_target_fields(fields)
            if target:
                code_lines.append(f"Зачислено · {target}")
            else:
                ext = d.artifact.get("external_id")
                if isinstance(ext, str):
                    code_lines.append(f"Зачислено · <code>{ext}</code>")
    truncated = max(0, len(deliveries) - _MAX_INLINE_CODES)

    body = f"<b>Заказ выдан</b> ✅\n\n{summary}\nСумма: <b>{amount}</b>"
    if code_lines:
        body += "\n\n" + "\n".join(code_lines)
    if truncated > 0:
        body += f"\n\n<i>… и ещё {truncated}. Открой приложение, чтобы увидеть все.</i>"

    return await tg.send_message(bot_token=token, chat_id=chat_id, text=body)


async def resend_guest_delivery_email(order_id: str, email: str) -> None:
    """Re-send the delivered-email (codes + a fresh access link) to a guest.

    Backs ``POST /orders/{id}/code-access``: a returning guest whose magic link
    expired asks us to re-mail it. Non-enumerating — silently returns when the
    order is unknown, is not a guest order matching ``email``, or has no
    deliveries yet — so it never reveals whether an order/email exists. Codes are
    only ever mailed to the order's own address, never to the caller's input.
    """
    normalised = email.strip().lower()
    async with get_session_factory()() as db:
        order = await _load_order(db, order_id)
        if order is None or (order.guest_email or "").lower() != normalised:
            return
        guest_email = order.guest_email
        deliveries = (
            (
                await db.execute(
                    select(Delivery)
                    .join(OrderItem, OrderItem.id == Delivery.order_item_id)
                    .where(OrderItem.order_id == order_id)
                    .order_by(Delivery.delivered_at)
                )
            )
            .scalars()
            .all()
        )
    if not deliveries:
        return
    codes, credited = _delivery_lines_for_email(deliveries)
    await _send_guest_email_delivered(
        order_id=order_id,
        guest_email=guest_email,
        web_base=get_settings().web_base_url or None,
        codes=codes,
        credited=credited,
    )


async def notify_order_failed(order_id: str, *, reason: str | None = None) -> bool:
    """Telegram: «Не удалось выполнить заказ»."""
    async with get_session_factory()() as db:
        order = await _load_order(db, order_id)
        if order is None:
            return False
        chat = await _resolve_chat_id(db, user_id=order.user_id)
        if chat is None:
            return False
        chat_id, _name = chat

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        return False

    summary = _summarise_order(order)
    body = f"<b>Заказ не выполнен</b>\n\n{summary}"
    if reason:
        body += f"\n\n<i>{reason}</i>"
    body += (
        "\n\nЕсли деньги были списаны — они вернутся автоматически. "
        "Напиши в поддержку, если возврат не пришёл за 24 часа."
    )
    return await tg.send_message(bot_token=token, chat_id=chat_id, text=body)


async def _load_order(db: AsyncSession, order_id: str) -> Order | None:
    """Eager-load the chain we need to summarise the order in one go.

    Walks ``item → sku → product`` because ``_summarise_order`` reads
    ``item.sku.product.brand``. Brand is ``lazy="joined"`` on ``Product``,
    so once ``product`` is loaded the brand comes for free. Async
    SQLAlchemy refuses lazy loads outside the request scope, so any
    missing eager load here surfaces as ``DetachedInstanceError`` when
    the background task tries to walk the relationship.
    """
    items_to_sku = selectinload(Order.items).selectinload(OrderItem.sku)
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            items_to_sku.selectinload(Sku.product)
            .joinedload(Product.brand)
            .selectinload(Brand.translations),
            items_to_sku.selectinload(Sku.product).selectinload(Product.translations),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ─── fire-and-forget scheduler ───────────────────────────────────────────────


def schedule(coro: Coroutine[Any, Any, bool]) -> None:
    """Run ``coro`` in the background and swallow every error.

    Used for fire-and-forget paths where there's no DB-transaction race —
    e.g. background reconciliation. Most order-event callers should prefer
    :func:`schedule_after_commit` so the notification only fires once the
    business transaction is durable.
    """

    async def _runner() -> None:
        try:
            await coro
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("notify.runner.crash", error=str(exc))

    asyncio.create_task(_runner())


def schedule_after_commit(
    db: AsyncSession,
    coro_factory: Callable[[], Coroutine[Any, Any, bool]],
) -> None:
    """Schedule a notification to run **after** the session commits.

    Two problems this solves:

    1. The notification opens its own ``AsyncSession`` to look up
       ``telegram_links`` etc. If we ``schedule()`` mid-transaction, that
       fresh session won't see uncommitted state — the user lookup may miss
       a brand-new ``TelegramLink``, deliveries won't be visible, etc.
    2. If the parent transaction rolls back, the user must not get a "your
       order shipped" ping for an order that never persisted.

    Hooks the SQLAlchemy ``after_commit`` event on the underlying sync
    session. On rollback nothing happens. ``coro_factory`` is a zero-arg
    callable so the coroutine isn't materialised until commit succeeds —
    avoiding "coroutine was never awaited" warnings on rollback paths.
    """

    sync_session = db.sync_session

    @event.listens_for(sync_session, "after_commit", once=True)
    def _fire(_s: Session) -> None:
        schedule(coro_factory())


__all__ = [
    "_send_guest_email_confirmation",
    "_send_guest_email_delivered",
    "notify_order_delivered",
    "notify_order_failed",
    "notify_order_paid",
    "schedule",
    "schedule_after_commit",
]
